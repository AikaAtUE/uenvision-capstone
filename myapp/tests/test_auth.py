import json

from django.test import TestCase, override_settings
from django.urls import reverse


from ..models import CustomUser

from .helpers import IsolatedDataMixin


class IdleTimeoutTests(TestCase):
    """Every role is logged out after IDLE_TIMEOUT_SECONDS without activity."""

    def login_as(self, role, email):
        user = CustomUser.objects.create_user(email=email, password="secret123",
                                              first_name="I", last_name="T", role=role)
        self.client.force_login(user)
        return user

    def age_session(self, seconds):
        import time
        session = self.client.session
        session["last_activity"] = int(time.time()) - seconds
        session.save()

    def test_idle_users_of_every_role_are_logged_out(self):
        pages = {CustomUser.Role.ADMINISTRATOR: "dashboard", CustomUser.Role.FACULTY: "dashboard",
                 CustomUser.Role.STUDENT: "student_dashboard", CustomUser.Role.ALUMNI: "student_dashboard"}
        for i, (role, page) in enumerate(pages.items()):
            with self.subTest(role=role):
                self.client.logout()
                self.login_as(role, f"idle{i}@ue.edu.ph")
                self.assertEqual(self.client.get(reverse(page)).status_code, 200)
                self.age_session(31 * 60)
                r = self.client.get(reverse(page))
                self.assertEqual(r.status_code, 302)
                self.assertTrue(r["Location"].startswith(reverse("login") + "?timeout=1"))
                self.assertNotIn("_auth_user_id", self.client.session)
                login = self.client.get(r["Location"])
                self.assertContains(login, "logged out after 30 minutes of inactivity")

    def test_activity_within_the_limit_keeps_the_session(self):
        self.login_as(CustomUser.Role.FACULTY, "active@ue.edu.ph")
        self.client.get(reverse("dashboard"))
        self.age_session(29 * 60)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.age_session(29 * 60)  # the request above refreshed the clock
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_ping_counts_as_activity(self):
        self.login_as(CustomUser.Role.STUDENT, "ping@ue.edu.ph")
        self.client.get(reverse("student_dashboard"))
        self.age_session(20 * 60)
        self.assertEqual(self.client.post(reverse("session_ping")).json(), {"ok": True})
        self.age_session(0)
        self.assertGreater(self.client.session["last_activity"], 0)

    def test_background_requests_do_not_keep_session_alive(self):
        self.login_as(CustomUser.Role.ADMINISTRATOR, "poll@ue.edu.ph")
        self.client.get(reverse("dashboard"))
        self.age_session(20 * 60)
        before = self.client.session["last_activity"]
        self.client.get(reverse("dashboard"), HTTP_X_BACKGROUND_REQUEST="1")
        self.assertEqual(self.client.session["last_activity"], before)
        self.age_session(31 * 60)
        r = self.client.get(reverse("dashboard"), HTTP_X_BACKGROUND_REQUEST="1")
        self.assertEqual(r.status_code, 401)
        self.assertTrue(r.json()["session_expired"])

    def test_expired_json_request_gets_401_not_redirect(self):
        self.login_as(CustomUser.Role.STUDENT, "json@ue.edu.ph")
        self.client.get(reverse("student_dashboard"))
        self.age_session(31 * 60)
        r = self.client.post(reverse("session_ping"), HTTP_ACCEPT="application/json")
        self.assertEqual(r.status_code, 401)


@override_settings(REQUIRE_EMAIL_VERIFICATION=True)
class EmailVerificationTests(TestCase):
    """Nobody has to confirm their email to use UEnvision. Students/alumni are reminded to; faculty aren't asked."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def signup(self, email="new@ue.edu.ph"):
        return self.client.post(reverse("signup"), {"last_name": "Cruz", "first_name": "Ana", "email": email,
                                                    "password": "longenough1", "password2": "longenough1"})

    def link_from_outbox(self):
        import re
        from django.core import mail
        return re.search(r"http://testserver(/verify-email/\S+/)", mail.outbox[-1].body).group(1)

    def unconfirmed_student(self, email="stu@ue.edu.ph"):
        return CustomUser.objects.create_user(email=email, password="longenough1", first_name="S", last_name="T",
                                              role=CustomUser.Role.STUDENT, email_verified=False)

    def test_faculty_signup_needs_no_confirmation(self):
        from django.core import mail
        r = self.signup()
        self.assertRedirects(r, reverse("dashboard"), fetch_redirect_response=False)
        self.assertIn("_auth_user_id", self.client.session)
        self.assertTrue(CustomUser.objects.get(email="new@ue.edu.ph").email_verified)
        self.assertFalse([m for m in mail.outbox if m.to == ["new@ue.edu.ph"]])

    def test_unconfirmed_student_can_log_in_and_confirm_later(self):
        from django.core import mail
        self.unconfirmed_student()
        r = self.client.post(reverse("login"), {"email": "stu@ue.edu.ph", "password": "longenough1"})
        self.assertRedirects(r, reverse("student_dashboard"), fetch_redirect_response=False)
        page = self.client.get(reverse("student_dashboard"))
        self.assertContains(page, "Please confirm your email.")
        settings_page = self.client.get(reverse("settings"))
        self.assertContains(settings_page, "Not confirmed")
        self.assertContains(settings_page, "Send confirmation link")
        r = self.client.post(reverse("send_my_verification"), {"next": reverse("student_dashboard")}, follow=True)
        self.assertContains(r, "We sent a confirmation link to stu@ue.edu.ph")
        self.assertEqual(mail.outbox[-1].to, ["stu@ue.edu.ph"])
        link = self.link_from_outbox()
        self.assertContains(self.client.get(link), "Email confirmed")
        self.assertTrue(CustomUser.objects.get(email="stu@ue.edu.ph").email_verified)
        self.assertContains(self.client.get(link), "This link doesn't work")  # only works once
        self.assertNotContains(self.client.get(reverse("student_dashboard")), "Please confirm your email.")
        self.assertContains(self.client.get(reverse("settings")), "Confirmed")

    def test_bad_link_is_rejected(self):
        self.unconfirmed_student()
        self.client.post(reverse("login"), {"email": "stu@ue.edu.ph", "password": "longenough1"})
        self.client.post(reverse("send_my_verification"))
        link = self.link_from_outbox()
        self.assertContains(self.client.get(link[:-3] + "xx/"), "This link doesn't work")
        self.assertFalse(CustomUser.objects.get(email="stu@ue.edu.ph").email_verified)

    def test_resend_is_rate_limited_and_does_not_reveal_accounts(self):
        from django.core import mail
        self.unconfirmed_student()
        self.client.post(reverse("resend_verification"), {"email": "stu@ue.edu.ph"})
        self.assertEqual(len(mail.outbox), 1)
        r = self.client.post(reverse("resend_verification"), {"email": "stu@ue.edu.ph"})
        self.assertContains(r, "Please wait 30 seconds")
        self.assertEqual(len(mail.outbox), 1)
        r = self.client.post(reverse("resend_verification"), {"email": "nobody@ue.edu.ph"})
        self.assertContains(r, "If <strong>nobody@ue.edu.ph</strong> has an account")
        self.assertEqual(len(mail.outbox), 1)

    def test_student_changes_email_in_settings(self):
        from django.core import mail
        user = self.unconfirmed_student()
        user.email_verified = True
        user.save()
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse("settings") + "?edit=1"), 'name="email" value="stu@ue.edu.ph"')
        r = self.client.post(reverse("update_account"), {"first_name": "S", "last_name": "T", "email": "not-an-email"})
        self.assertRedirects(r, reverse("settings") + "?edit=1", fetch_redirect_response=False)
        user.refresh_from_db()
        self.assertEqual(user.email, "stu@ue.edu.ph")
        r = self.client.post(reverse("update_account"), {"first_name": "Sam", "middle_name": "Q", "last_name": "Tan",
                                                         "email": "sam.tan@ue.edu.ph"}, follow=True)
        self.assertContains(r, "We sent a confirmation link to sam.tan@ue.edu.ph")
        user.refresh_from_db()
        self.assertEqual((user.first_name, user.middle_name, user.last_name, user.email),
                         ("Sam", "Q", "Tan", "sam.tan@ue.edu.ph"))
        self.assertFalse(user.email_verified)
        self.assertEqual(mail.outbox[-1].to, ["sam.tan@ue.edu.ph"])

    def test_faculty_changes_email_without_confirming(self):
        from django.core import mail
        user = CustomUser.objects.create_user(email="fac@ue.edu.ph", password="longenough1", first_name="F",
                                              last_name="C", role=CustomUser.Role.FACULTY)
        CustomUser.objects.create_user(email="taken@ue.edu.ph", password="longenough1", first_name="T", last_name="K")
        self.client.force_login(user)
        r = self.client.post(reverse("update_account"), {"first_name": "F", "last_name": "C", "email": "taken@ue.edu.ph"},
                             follow=True)
        self.assertContains(r, "An account with this email already exists.")
        self.client.post(reverse("update_account"), {"first_name": "F", "last_name": "C", "email": "fac2@gmail.com"})
        user.refresh_from_db()
        self.assertEqual(user.email, "fac2@gmail.com")
        self.assertTrue(user.email_verified)
        self.assertEqual(len(mail.outbox), 0)
        self.assertNotContains(self.client.get(reverse("settings")), "Not confirmed")

    def test_existing_and_admin_made_accounts_need_no_confirmation(self):
        user = CustomUser.objects.create_user(email="old@ue.edu.ph", password="secret123",
                                              first_name="O", last_name="L")
        self.assertTrue(user.email_verified)
        r = self.client.post(reverse("login"), {"email": "old@ue.edu.ph", "password": "secret123"})
        self.assertEqual(r.status_code, 302)

    @override_settings(REQUIRE_EMAIL_VERIFICATION=False)
    def test_without_email_settings_signup_logs_in_directly(self):
        r = self.signup("direct@ue.edu.ph")
        self.assertRedirects(r, reverse("dashboard"), fetch_redirect_response=False)
        self.assertTrue(CustomUser.objects.get(email="direct@ue.edu.ph").email_verified)


class ForgotPasswordTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.user = CustomUser.objects.create_user(email="Paeng@ue.edu.ph", password="oldpass123",
                                                   first_name="Pa", last_name="Eng")

    def test_reset_by_email_link(self):
        from django.core import mail
        r = self.client.post(reverse("forgot_password"), {"email": "paeng@UE.edu.ph"})   # any letter case
        self.assertContains(r, "emailed it a link to reset")
        self.assertEqual(mail.outbox[0].to, ["Paeng@ue.edu.ph"])
        link = mail.outbox[0].body.split("http://testserver", 1)[1].split()[0]
        self.assertContains(self.client.get(link), "Choose a new password")
        r = self.client.post(link, {"password": "short", "password2": "short"})
        self.assertContains(r, "at least 8")
        r = self.client.post(link, {"password": "newpass123", "password2": "newpass123"})
        self.assertContains(r, "Password changed")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("newpass123"))
        # the link only works once
        self.assertContains(self.client.get(link), "This link doesn")

    def test_unknown_email_gets_the_same_answer_and_no_email(self):
        from django.core import mail
        r = self.client.post(reverse("forgot_password"), {"email": "nobody@ue.edu.ph"})
        self.assertContains(r, "If <strong>nobody@ue.edu.ph</strong> has a UEnvision account")
        self.assertEqual(len(mail.outbox), 0)

    def test_rate_limited(self):
        from django.core import mail
        self.client.post(reverse("forgot_password"), {"email": "paeng@ue.edu.ph"})
        r = self.client.post(reverse("forgot_password"), {"email": "paeng@ue.edu.ph"})
        self.assertContains(r, "Please wait 30 seconds")
        self.assertEqual(len(mail.outbox), 1)

    def test_old_reset_address_redirects(self):
        self.assertRedirects(self.client.get(reverse("reset_password")), reverse("forgot_password"))


class LoginLimitTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            "limit@ue.edu.ph", "right-password1", first_name="Li", last_name="Mit")

    def attempt(self, email="limit@ue.edu.ph", password="wrong-password", ip="10.0.0.1"):
        return self.client.post(reverse("login"), {"email": email, "password": password}, REMOTE_ADDR=ip)

    def test_limits(self):
        from .. import login_limits
        self.assertEqual((login_limits.MAX_PER_EMAIL, login_limits.WINDOW_SECONDS), (20, 30))
        self.assertGreater(login_limits.MAX_PER_IP, login_limits.MAX_PER_EMAIL)

    def test_twenty_wrong_passwords_pause_that_email_for_30_seconds(self):
        for _ in range(19):
            self.assertEqual(self.attempt().status_code, 200)
        self.assertEqual(self.attempt().status_code, 200)   # the 20th is still answered normally
        resp = self.attempt(password="right-password1")
        self.assertEqual(resp.status_code, 429)
        self.assertContains(resp, "Too many login attempts. Try again in 30 seconds", status_code=429)
        self.assertNotIn("_auth_user_id", self.client.session)
        # from another computer too (it's the account that is paused)
        self.assertEqual(self.attempt(password="right-password1", ip="10.0.0.2").status_code, 429)
        # other accounts are fine
        CustomUser.objects.create_user("other@ue.edu.ph", "other-password1", first_name="O", last_name="T")
        self.assertRedirects(self.attempt("other@ue.edu.ph", "other-password1"), reverse("dashboard"))

    def test_pause_ends_after_the_window(self):
        from unittest import mock

        from .. import login_limits

        for _ in range(20):
            self.attempt()
        later = login_limits.time.time() + login_limits.WINDOW_SECONDS + 1
        with mock.patch.object(login_limits.time, "time", return_value=later):
            self.assertRedirects(self.attempt(password="right-password1"), reverse("dashboard"))

    def test_successful_login_resets_the_count(self):
        for _ in range(19):
            self.attempt()
        self.assertRedirects(self.attempt(password="right-password1"), reverse("dashboard"))
        self.client.logout()
        for _ in range(19):
            self.assertEqual(self.attempt().status_code, 200)

    def test_same_message_for_emails_without_an_account(self):
        for _ in range(20):
            self.attempt("nobody@ue.edu.ph")
        self.assertContains(self.attempt("nobody@ue.edu.ph"), "Too many login attempts", status_code=429)

    def test_fifty_failures_from_one_computer_pause_it(self):
        for i in range(50):
            self.attempt(f"guess{i}@ue.edu.ph")
        self.assertEqual(self.attempt(password="right-password1").status_code, 429)
        self.assertRedirects(self.attempt(password="right-password1", ip="10.0.0.9"), reverse("dashboard"))

    def test_nginx_real_ip_header_is_used(self):
        for i in range(50):
            self.client.post(reverse("login"), {"email": f"g{i}@ue.edu.ph", "password": "x"},
                             REMOTE_ADDR="127.0.0.1", HTTP_X_REAL_IP="203.0.113.5")
        blocked = self.client.post(reverse("login"), {"email": "limit@ue.edu.ph", "password": "right-password1"},
                                   REMOTE_ADDR="127.0.0.1", HTTP_X_REAL_IP="203.0.113.5")
        self.assertEqual(blocked.status_code, 429)
        ok = self.client.post(reverse("login"), {"email": "limit@ue.edu.ph", "password": "right-password1"},
                              REMOTE_ADDR="127.0.0.1", HTTP_X_REAL_IP="203.0.113.6")
        self.assertRedirects(ok, reverse("dashboard"))

    def test_password_reset_link_lifts_the_pause(self):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        for _ in range(20):
            self.attempt()
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        url = reverse("reset_password_confirm", args=[uid, default_token_generator.make_token(self.user)])
        self.client.post(url, {"password": "brand-new-pass", "password2": "brand-new-pass"})
        self.assertRedirects(self.attempt(password="brand-new-pass"), reverse("dashboard"))

    def test_admin_login_goes_through_the_limited_login_page(self):
        resp = self.client.get("/admin/login/?next=/admin/")
        self.assertRedirects(resp, reverse("login") + "?next=%2Fadmin%2F", fetch_redirect_response=False)
        self.assertRedirects(self.client.get("/admin/"), "/admin/login/?next=/admin/", fetch_redirect_response=False)


class KeepFormInputsTests(IsolatedDataMixin, TestCase):
    """A failed login/sign-up keeps what was typed (never the login password), and
    the login page can be posted with fetch() so it doesn't reload."""

    def setUp(self):
        super().setUp()
        self.user = CustomUser.objects.create_user("keep@ue.edu.ph", "right-password1",
                                                   first_name="Ke", last_name="Ep")

    def test_failed_login_keeps_the_email_but_not_the_password(self):
        r = self.client.post(reverse("login"), {"email": "keep@ue.edu.ph", "password": "wrong-password"})
        self.assertContains(r, "Invalid email or password.")
        self.assertContains(r, 'value="keep@ue.edu.ph"')
        self.assertNotContains(r, "wrong-password")

    def test_login_with_fetch_answers_in_json(self):
        ajax = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
        r = self.client.post(reverse("login"), {"email": "keep@ue.edu.ph", "password": "wrong"}, **ajax)
        self.assertEqual(r.json(), {"ok": False, "error": "Invalid email or password."})
        self.assertNotIn("_auth_user_id", self.client.session)
        r = self.client.post(reverse("login") + "?next=/settings/",
                             {"email": "keep@ue.edu.ph", "password": "right-password1"}, **ajax)
        self.assertEqual(r.json(), {"ok": True, "redirect": "/settings/"})
        self.assertIn("_auth_user_id", self.client.session)
        self.client.logout()
        r = self.client.post(reverse("login"), {"email": "keep@ue.edu.ph", "password": "right-password1",
                                                "next": "https://evil.example/"}, **ajax)
        self.assertEqual(r.json()["redirect"], reverse("dashboard"))

    def test_paused_login_with_fetch(self):
        ajax = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
        for _ in range(20):
            self.client.post(reverse("login"), {"email": "keep@ue.edu.ph", "password": "wrong"}, **ajax)
        r = self.client.post(reverse("login"), {"email": "keep@ue.edu.ph", "password": "right-password1"}, **ajax)
        self.assertEqual(r.status_code, 429)
        self.assertIn("Too many login attempts", r.json()["error"])

    def test_failed_signup_keeps_every_field(self):
        r = self.client.post(reverse("signup"), {
            "last_name": "Cruz", "first_name": "Ana", "middle_name": "Reyes", "email": "keep@ue.edu.ph",
            "password": "long-enough1", "password2": "long-enough1"})
        self.assertContains(r, "An account with this email already exists.")
        for value in ("Cruz", "Ana", "Reyes", "keep@ue.edu.ph", "long-enough1"):
            self.assertContains(r, f'value="{value}"')

    def test_signup_and_register_show_the_password_requirement(self):
        r = self.client.get(reverse("signup"))
        self.assertContains(r, 'data-min-length="8">At least 8 characters</li>')
        self.assertContains(r, 'minlength="8"')

    def test_failed_register_keeps_the_typed_values(self):
        r = self.client.post(reverse("register"), {
            "as": "student", "consent": "on", "first_name": "Juan", "last_name": "Dela Cruz",
            "student_number": "2023-1", "course": "BSIT", "year_level": "1", "section": "TN11",
            "email": "juan@ue.edu.ph", "password": "secret123", "password2": "secret124", "method": "password"})
        self.assertContains(r, "Passwords do not match.")
        for value in ("juan@ue.edu.ph", "Juan", "Dela Cruz", "2023-1", "TN11"):
            self.assertContains(r, f'value="{value}"')
        self.assertNotContains(r, 'value="secret123"')   # passwords are never sent back
        self.assertContains(r, 'data-min-length="8">At least 8 characters</li>')
