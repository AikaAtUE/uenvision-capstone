"""Google sign-in (myapp/google_auth.py): existing accounts are found by email, new
students/alumni come from the registration page, and nobody else is signed up."""
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from ..models import CustomUser
from ..google_auth import PENDING_KEY

KEYS = {"GOOGLE_CLIENT_ID": "test.apps.googleusercontent.com", "GOOGLE_CLIENT_SECRET": "test"}


@override_settings(**KEYS)
class GoogleSignInTests(TestCase):
    def google_login(self, email, pending=None):
        """Runs what happens when Google sends someone back, for a Google account with `email`."""
        from allauth.account.models import EmailAddress
        from allauth.core import context
        from allauth.socialaccount.helpers import complete_social_login
        from allauth.socialaccount.models import SocialAccount, SocialLogin

        request = RequestFactory().get("/auth/google/login/callback/")
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = AnonymousUser()
        if pending:
            request.session[PENDING_KEY] = pending
        from allauth.socialaccount.adapter import get_adapter
        with context.request_context(request):
            provider = get_adapter(request).get_provider(request, "google")
        login = SocialLogin(provider=provider, user=CustomUser(email=email, first_name="Google", last_name="Name"),
                            account=SocialAccount(provider="google", uid=email, extra_data={"email": email}),
                            email_addresses=[EmailAddress(email=email, verified=True, primary=True)])
        login.state = {"process": "login", "next": "/survey/student/"}
        with context.request_context(request):
            response = complete_social_login(request, login)
        return request, response

    def test_existing_account_logs_in_and_keeps_its_password(self):
        user = CustomUser.objects.create_user(email="prof@ue.edu.ph", password="secret123", first_name="P",
                                              last_name="R", role=CustomUser.Role.FACULTY)
        request, response = self.google_login("PROF@ue.edu.ph")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(request.session["_auth_user_id"]), user.pk)
        user.refresh_from_db()
        self.assertTrue(user.check_password("secret123"))
        self.assertEqual(CustomUser.objects.count(), 1)

    def test_registration_with_google_makes_the_student_account(self):
        pending = {"role": "student", "first_name": "Ana", "last_name": "Reyes", "target_role": "qa",
                   "info": {"student_number": "2023-9", "course": "BSCS", "year_level": "2", "section": "A1"}}
        request, response = self.google_login("ana.reyes@ue.edu.ph", pending)
        self.assertRedirects(response, "/survey/student/", fetch_redirect_response=False)
        user = CustomUser.objects.get(email="ana.reyes@ue.edu.ph")
        self.assertEqual((user.role, user.get_full_name(), user.target_role), ("student", "Ana Reyes", "qa"))
        self.assertEqual(user.learner_info["section"], "A1")
        self.assertFalse(user.has_usable_password())
        self.assertNotIn(PENDING_KEY, request.session)

    def test_unknown_google_account_is_not_signed_up(self):
        request, response = self.google_login("stranger@gmail.com")
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)
        self.assertFalse(CustomUser.objects.exists())

    def test_students_may_register_with_any_google_account(self):
        pending = {"role": "student", "first_name": "Ana", "last_name": "Reyes",
                   "info": {"student_number": "2023-9", "course": "BSCS", "year_level": "2", "section": "A1"}}
        request, response = self.google_login("ana@gmail.com", pending)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(CustomUser.objects.get(email="ana@gmail.com").role, CustomUser.Role.STUDENT)

    def test_alumni_may_register_with_any_google_account(self):
        pending = {"role": "alumni", "first_name": "Ana", "last_name": "Reyes",
                   "info": {"student_number": "2019-1", "course": "BSIT", "year_graduated": "2023"}}
        request, response = self.google_login("ana.reyes@gmail.com", pending)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(CustomUser.objects.get(email="ana.reyes@gmail.com").role, CustomUser.Role.ALUMNI)

    def test_buttons_and_registration_start(self):
        self.assertContains(self.client.get(reverse("login")), "Continue with Google")
        r = self.client.post(reverse("register"), {
            "as": "student", "consent": "on", "first_name": "Ana", "last_name": "Reyes", "student_number": "1",
            "course": "BSIT", "year_level": "2", "section": "A", "method": "google"})
        self.assertTrue(r["Location"].startswith("https://accounts.google.com/"))
        self.assertEqual(self.client.session[PENDING_KEY]["info"]["section"], "A")

    @override_settings(GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_SECRET="")
    def test_no_buttons_without_keys(self):
        self.assertNotContains(self.client.get(reverse("login")), "Continue with Google")
        self.assertNotContains(self.client.get(reverse("register"), {"as": "student"}), "Continue with Google")
