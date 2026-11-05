"""Google sign-in (myapp/google_auth.py): existing accounts are found by email; a new
Google account is held until they pick student / alumni / faculty and finish the form,
which then shows "Signed in using ... through Google" with the names filled in."""
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from ..models import CustomUser
from ..google_auth import HELD_KEY, PENDING_KEY

KEYS = {"GOOGLE_CLIENT_ID": "test.apps.googleusercontent.com", "GOOGLE_CLIENT_SECRET": "test"}
STUDENT = {"as": "student", "consent": "on", "first_name": "Ana", "last_name": "Reyes", "student_number": "2023-9",
           "course": "BSCS", "year_level": "2", "section": "A1"}


@override_settings(**KEYS)
class GoogleSignInTests(TestCase):
    def google_login(self, email, first="Ana", last="Reyes"):
        """Runs what happens when Google sends someone back, for a Google account with
        `email`, in the test client's session."""
        from allauth.account.models import EmailAddress
        from allauth.core import context
        from allauth.socialaccount.adapter import get_adapter
        from allauth.socialaccount.helpers import complete_social_login
        from allauth.socialaccount.models import SocialAccount, SocialLogin

        request = RequestFactory().get("/auth/google/login/callback/")
        request.session = self.client.session
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = AnonymousUser()
        with context.request_context(request):
            provider = get_adapter(request).get_provider(request, "google")
        login = SocialLogin(provider=provider, user=CustomUser(email=email, first_name=first, last_name=last),
                            account=SocialAccount(provider="google", uid=email, extra_data={"email": email}),
                            email_addresses=[EmailAddress(email=email, verified=True, primary=True)])
        login.state = {"process": "login"}
        with context.request_context(request):
            response = complete_social_login(request, login)
        request.session.save()
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

    def test_new_google_account_from_login_is_asked_who_they_are(self):
        request, response = self.google_login("ana@gmail.com")
        self.assertRedirects(response, reverse("signup"), fetch_redirect_response=False)
        self.assertFalse(CustomUser.objects.exists())   # nothing is made until they finish
        r = self.client.get(reverse("signup"))
        self.assertContains(r, "Signed in using <strong>ana@gmail.com</strong> through Google")
        self.assertContains(r, "Hi Ana!")
        self.assertContains(r, "I'm a current student")

    def test_student_form_is_filled_in_and_creates_the_account(self):
        self.google_login("ana@gmail.com")
        r = self.client.get(reverse("register"), {"as": "student", "role": "qa"})
        self.assertContains(r, "Signed in using <strong>ana@gmail.com</strong> through Google")
        self.assertContains(r, 'name="first_name" value="Ana"')
        self.assertContains(r, 'name="last_name" value="Reyes"')
        self.assertNotContains(r, 'name="password"')
        self.assertNotContains(r, 'name="email"')
        r = self.client.post(reverse("register"), {**STUDENT, "role": "qa"})
        self.assertEqual(r.status_code, 302)
        user = CustomUser.objects.get(email="ana@gmail.com")
        self.assertEqual((user.role, user.get_full_name(), user.target_role), ("student", "Ana Reyes", "qa"))
        self.assertEqual(user.learner_info["section"], "A1")
        self.assertFalse(user.has_usable_password())
        self.assertTrue(user.socialaccount_set.filter(provider="google").exists())
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        self.assertNotIn(HELD_KEY, self.client.session)

    def test_alumni_too(self):
        self.google_login("ana.reyes@gmail.com")
        self.client.post(reverse("register"), {"as": "alumni", "consent": "on", "first_name": "Ana",
                                               "last_name": "Reyes", "student_number": "2019-1",
                                               "course": "BSIT", "year_graduated": "2023"})
        self.assertEqual(CustomUser.objects.get(email="ana.reyes@gmail.com").role, CustomUser.Role.ALUMNI)

    def test_faculty_form_is_filled_in_and_middle_name_is_optional(self):
        self.google_login("maria.santos@ue.edu.ph", "Maria", "Santos")
        r = self.client.get(reverse("signup"), {"as": "faculty"})
        self.assertContains(r, "Signed in using <strong>maria.santos@ue.edu.ph</strong> through Google")
        self.assertContains(r, "Middle name (optional)")
        self.assertNotContains(r, 'name="password"')
        r = self.client.post(reverse("signup"), {"as": "faculty", "last_name": "Santos", "first_name": "Maria",
                                                 "middle_name": ""})
        self.assertRedirects(r, reverse("professor_survey"), fetch_redirect_response=False)
        user = CustomUser.objects.get(email="maria.santos@ue.edu.ph")
        self.assertEqual((user.role, user.is_approved, user.middle_name), ("faculty", False, ""))

    def test_continue_with_google_on_the_form_keeps_what_they_typed(self):
        r = self.client.post(reverse("google_signup_start"),
                             {"as": "student", "student_number": "2023-9", "password": "x",
                              "next": reverse("register") + "?as=student"})
        self.assertTrue(r["Location"].startswith("https://accounts.google.com/"))
        pending = self.client.session[PENDING_KEY]
        self.assertEqual(pending["return_to"], "/register/?as=student")
        self.assertNotIn("password", pending["form"])
        request, response = self.google_login("ana@gmail.com")
        self.assertRedirects(response, "/register/?as=student", fetch_redirect_response=False)
        r = self.client.get(reverse("register"), {"as": "student"})
        self.assertContains(r, 'name="student_number" value="2023-9"')
        self.assertContains(r, 'name="first_name" value="Ana"')

    def test_email_taken_meanwhile_is_not_duplicated(self):
        self.google_login("ana@gmail.com")
        CustomUser.objects.create_user(email="ANA@gmail.com", password="secret123", first_name="A", last_name="R")
        r = self.client.post(reverse("register"), STUDENT)
        self.assertContains(r, "already exists")
        self.assertEqual(CustomUser.objects.count(), 1)

    @override_settings(GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_SECRET="")
    def test_no_buttons_without_keys(self):
        self.assertNotContains(self.client.get(reverse("login")), "Continue with Google")
        self.assertNotContains(self.client.get(reverse("register"), {"as": "student"}), "Continue with Google")
