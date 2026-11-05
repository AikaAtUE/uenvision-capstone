"""Sign-up asks who you are (student / alumni / faculty) first, and an administrator can
move someone who signed up as faculty by mistake, with their survey answers, to Student.
Every survey also says what it is for at the top."""
from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import CurriculumSurveyResponse, CustomUser, Notification
from .helpers import IsolatedDataMixin

KEYS = {"GOOGLE_CLIENT_ID": "test.apps.googleusercontent.com", "GOOGLE_CLIENT_SECRET": "test"}
PROFESSOR_ANSWER = {"consent": True, "consent_at": "2026-11-01T08:00:00+00:00", "subjects": [
    {"code": "CCS0003", "name": "Computer Programming 1", "skills": [{"name": "Python", "level": "applied"}]},
    {"code": "ELEC1", "name": "Mobile Dev", "custom": True, "programs": ["BSIT"],
     "skills": [{"name": "Kotlin", "level": "introduced"}]}]}


class SignupAsksWhoYouAreTests(TestCase):
    def test_signup_page_offers_all_three_and_no_form_yet(self):
        r = self.client.get(reverse("signup"))
        for text in ("I'm a current student", "I'm an alumni / fresh graduate", "I'm a faculty member"):
            self.assertContains(r, text)
        self.assertNotContains(r, 'id="signup-form"')
        self.assertContains(self.client.get(reverse("login")), "as a student, alumni or faculty")

    def test_student_and_alumni_go_to_registration(self):
        self.assertRedirects(self.client.get(reverse("signup"), {"as": "student"}),
                             reverse("register") + "?as=student", fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse("signup"), {"as": "alumni"}),
                             reverse("register") + "?as=alumni", fetch_redirect_response=False)

    def test_posting_without_choosing_makes_no_account(self):
        r = self.client.post(reverse("signup"), {"last_name": "A", "first_name": "B", "email": "x@gmail.com",
                                                 "password": "longenough1", "password2": "longenough1"})
        self.assertContains(r, "Please choose whether you are a student, an alumni or faculty.")
        self.assertFalse(CustomUser.objects.exists())

    def test_faculty_form_needs_no_ue_email(self):
        self.assertContains(self.client.get(reverse("signup"), {"as": "faculty"}), "Signing up as <strong>Faculty</strong>")
        self.client.post(reverse("signup"), {"as": "faculty", "last_name": "A", "first_name": "B", "email": "x@gmail.com",
                                             "password": "longenough1", "password2": "longenough1"})
        user = CustomUser.objects.get(email="x@gmail.com")
        self.assertEqual((user.role, user.is_approved), ("faculty", False))

    @override_settings(**KEYS)
    def test_faculty_can_sign_up_with_google(self):
        self.assertContains(self.client.get(reverse("signup"), {"as": "faculty"}), "Continue with Google")
        r = self.client.post(reverse("google_signup_start"), {"as": "faculty", "last_name": "Santos",
                                                              "next": reverse("signup") + "?as=faculty"})
        self.assertTrue(r["Location"].startswith("https://accounts.google.com/"))
        from ..google_auth import PENDING_KEY
        self.assertEqual(self.client.session[PENDING_KEY]["return_to"], "/signup/?as=faculty")


class MoveFacultyToStudentTests(IsolatedDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = CustomUser.objects.create_user(email="admin@ue.edu.ph", password="secret123", first_name="Ad",
                                                    last_name="Min", role=CustomUser.Role.ADMINISTRATOR)
        self.wrong = CustomUser.objects.create_user(email="kid@gmail.com", password="secret123", first_name="Juan",
                                                    last_name="Cruz", role=CustomUser.Role.FACULTY, is_approved=False)
        Notification.objects.create(recipient=self.admin, kind=Notification.FACULTY_SIGNUP, message="x",
                                    subject_user=self.wrong)
        self.answer = CurriculumSurveyResponse.objects.create(respondent_type="professor", user=self.wrong,
                                                              data=PROFESSOR_ANSWER)
        self.client.force_login(self.admin)

    def test_move_turns_account_and_answers_into_a_student(self):
        page = self.client.get(reverse("accounts"))
        self.assertContains(page, 'data-action="move"')
        r = self.client.post(reverse("account_move_to_student", args=[self.wrong.pk]))
        self.assertRedirects(r, reverse("accounts"), fetch_redirect_response=False)
        self.wrong.refresh_from_db()
        self.answer.refresh_from_db()
        self.assertEqual((self.wrong.role, self.wrong.is_approved), ("student", True))
        self.assertEqual(self.answer.respondent_type, "student")
        self.assertEqual([s["code"] for s in self.answer.data["subjects"]], ["CCS0003", "ELEC1"])
        self.assertEqual(self.answer.data["subjects"][0]["skills"], [{"name": "Python", "level": "applied"}])
        self.assertEqual(self.answer.data["personal_info"]["ue_email"], "kid@gmail.com")
        self.assertFalse(Notification.objects.filter(read_at__isnull=True).exists())

        # as the student: their dashboard, My skills and survey all work with the moved answer
        self.client.force_login(self.wrong)
        self.assertEqual(self.client.get(reverse("student_dashboard")).status_code, 200)
        self.assertContains(self.client.get(reverse("my_skills")), "CCS0003")
        self.assertEqual(self.client.get(reverse("student_survey")).status_code, 200)

    def test_only_faculty_and_only_administrators(self):
        student = CustomUser.objects.create_user(email="s@gmail.com", password="secret123", first_name="S",
                                                 last_name="T", role=CustomUser.Role.STUDENT)
        self.client.post(reverse("account_move_to_student", args=[self.admin.pk]))
        self.assertEqual(CustomUser.objects.get(pk=self.admin.pk).role, "administrator")
        self.client.force_login(student)
        self.client.post(reverse("account_move_to_student", args=[self.wrong.pk]))
        self.assertEqual(CustomUser.objects.get(pk=self.wrong.pk).role, "faculty")

    def test_editing_the_role_to_student_moves_the_answers_too(self):
        self.client.post(reverse("account_edit", args=[self.wrong.pk]), {
            "last_name": "Cruz", "first_name": "Juan", "email": "kid@gmail.com", "account_type": "student"})
        self.answer.refresh_from_db()
        self.assertEqual(self.answer.respondent_type, "student")


class SurveyPurposeTests(IsolatedDataMixin, TestCase):
    def test_every_survey_starts_with_its_purpose(self):
        admin = CustomUser.objects.create_user(email="admin@ue.edu.ph", password="secret123", first_name="Ad",
                                               last_name="Min", role=CustomUser.Role.ADMINISTRATOR)
        self.client.force_login(admin)
        for name in ("student_survey", "alumni_survey", "professor_survey"):
            self.assertContains(self.client.get(reverse(name)), "Purpose of this survey:", count=1)
        self.assertContains(self.client.get(reverse("feedback")), "Purpose of this survey:", count=3)
