"""The student / alumni survey's "About you": editable, saved to the account, checked like registration."""
import json

from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import CurriculumSurveyResponse, CustomUser
from .helpers import IsolatedDataMixin


def learner(email="juan@ue.edu.ph", role=CustomUser.Role.STUDENT, number="2022606551", **info):
    base = ({"student_number": number, "course": "BSIT", "year_level": "1", "section": "TN11"}
            if role == CustomUser.Role.STUDENT else {"student_number": number, "course": "BSIT", "year_graduated": "2025"})
    return CustomUser.objects.create_user(email=email, password="secret123", first_name="Juan", last_name="Cruz",
                                          role=role, learner_info={**base, **info})


class AboutYouSaveTests(TestCase):
    url = reverse("learner_about_save")

    def post(self, **data):
        return self.client.post(self.url, data=json.dumps(data), content_type="application/json")

    def student_fields(self, **over):
        return {"first_name": "Juan", "middle_name": "", "last_name": "Dela Cruz", "course": "BSCS",
                "student_number": "2022606552", "year_level": "2", "section": "TN21", **over}

    def test_saves_name_and_details_to_the_account(self):
        user = learner()
        self.client.force_login(user)
        r = self.post(**self.student_fields(middle_name="  Santos "))
        self.assertEqual(r.status_code, 200, r.content)
        user.refresh_from_db()
        self.assertEqual((user.first_name, user.middle_name, user.last_name), ("Juan", "Santos", "Dela Cruz"))
        self.assertEqual(user.learner_info, {"student_number": "2022606552", "course": "BSCS",
                                             "year_level": "2", "section": "TN21"})
        about = r.json()["about"]
        self.assertEqual((about["name"], about["student_number"], about["year_label"], about["section"]),
                         ("Juan Santos Dela Cruz", "2022606552", "2nd Year", "TN21"))
        self.assertEqual(about["email"], "juan@ue.edu.ph")

    def test_alumni_details(self):
        user = learner("ana@gmail.com", CustomUser.Role.ALUMNI)
        self.client.force_login(user)
        r = self.post(first_name="Ana", last_name="Reyes", course="BSIT", student_number="2019-1", year_graduated="2024")
        self.assertEqual(r.status_code, 200, r.content)
        user.refresh_from_db()
        self.assertEqual(user.learner_info["year_graduated"], "2024")
        self.assertEqual(self.post(first_name="Ana", last_name="Reyes", course="BSIT", student_number="2019-1",
                                   year_graduated="1990").status_code, 400)

    def test_checked_like_registration(self):
        user = learner()
        learner("other@ue.edu.ph", number="2022606552")
        self.client.force_login(user)
        for bad, message in [({"first_name": " "}, "first and last name"),
                             ({"course": "BSXX"}, "course"),
                             ({"year_level": "9"}, "year level"),
                             ({"section": ""}, "section"),
                             ({"student_number": "x" * 31}, "too long"),
                             ({"student_number": "2022606552"}, "Another account already uses this student number")]:
            r = self.post(**self.student_fields(**bad))
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn(message, r.json()["error"])
        user.refresh_from_db()
        self.assertEqual(user.learner_info["student_number"], "2022606551")   # nothing saved
        # keeping your own number is fine
        self.assertEqual(self.post(**self.student_fields(student_number="2022606551")).status_code, 200)

    def test_email_is_not_changed_here(self):
        user = learner()
        self.client.force_login(user)
        self.post(**self.student_fields(email="someone.else@ue.edu.ph"))
        user.refresh_from_db()
        self.assertEqual(user.email, "juan@ue.edu.ph")

    def test_only_logged_in_students_and_alumni(self):
        self.assertEqual(self.post(**self.student_fields()).status_code, 302)
        fac = CustomUser.objects.create_user(email="f@ue.edu.ph", password="secret123", first_name="F", last_name="A")
        self.client.force_login(fac)
        self.assertEqual(self.post(**self.student_fields()).status_code, 403)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    @override_settings(REQUIRE_LEARNER_SURVEY=True)
    def test_works_before_the_first_survey_answer(self):
        user = learner()
        self.client.force_login(user)
        self.assertEqual(self.post(**self.student_fields()).status_code, 200)


class AboutYouSurveyPageTests(IsolatedDataMixin, TestCase):
    def test_fields_are_editable_and_email_points_to_settings(self):
        user = learner()
        self.client.force_login(user)
        html = self.client.get(reverse("student_survey")).content.decode()
        for field in ("first_name", "middle_name", "last_name", "student_number", "course", "year_level", "section"):
            self.assertIn(f'data-about-field="{field}"', html)
        self.assertIn(f'data-about-save="{reverse("learner_about_save")}"', html)
        self.assertIn('id="student-email" value="juan@ue.edu.ph" readonly', html)
        self.assertIn("changed in <a class=\"link-inline\" href=\"/settings/?edit=1\">Settings</a>", html)
        self.assertNotIn('id="student-name" value="Juan Cruz" readonly', html)
        self.assertIn('Student no. <span data-about="student_number">2022606551</span>', html)
        self.assertIn('id="student-number" value="2022606551"', html)

    def test_alumni_page_too(self):
        user = learner("ana@gmail.com", CustomUser.Role.ALUMNI)
        self.client.force_login(user)
        html = self.client.get(reverse("alumni_survey")).content.decode()
        self.assertIn('data-about-field="year_graduated"', html)
        self.assertIn('id="alumni-first" value="Juan"', html)
        self.assertIn('id="alumni-email" value="ana@gmail.com" readonly', html)

    def test_drafts_never_overwrite_account_details(self):
        from pathlib import Path
        js = (Path(__file__).resolve().parent.parent / "static" / "myapp" / "curriculum-survey.js").read_text(encoding="utf-8")
        self.assertIn("el.hasAttribute('data-from-account')", js)

    def submit(self, **personal):
        info = {"name": "ignored", "ue_email": "ignored@ue.edu.ph", "course": "BSIT", "student_number": "2022606551",
                "year_level": 1, "section": "TN11", **personal}
        payload = {"consent": True, "personal_info": info, "has_previous": False,
                   "subjects": [{"code": "CCP 1101", "term": "current", "skills": [{"name": "SQL", "level": "applied"}]}]}
        return self.client.post(reverse("student_survey_submit"), data=json.dumps(payload), content_type="application/json")

    def test_submitting_the_survey_saves_edited_details_too(self):
        user = learner()
        self.client.force_login(user)
        r = self.submit(first_name="Juan", middle_name="", last_name="Dela Cruz", student_number="2022606559", section="TN12")
        self.assertEqual(r.status_code, 200, r.content)
        user.refresh_from_db()
        self.assertEqual(user.get_full_name(), "Juan Dela Cruz")
        self.assertEqual((user.learner_info["student_number"], user.learner_info["section"]), ("2022606559", "TN12"))
        saved = CurriculumSurveyResponse.objects.get().data["personal_info"]
        self.assertEqual((saved["name"], saved["ue_email"], saved["student_number"]),
                         ("Juan Dela Cruz", "juan@ue.edu.ph", "2022606559"))   # email stays the account's
        self.assertNotIn("first_name", saved)

    def test_submitting_with_someone_elses_student_number_is_refused(self):
        user = learner()
        learner("other@ue.edu.ph", number="2022606552")
        self.client.force_login(user)
        r = self.submit(student_number="2022606552")
        self.assertEqual(r.status_code, 400)
        self.assertIn("student number", r.json()["error"])


class DummyStudentNumberTests(TestCase):
    def test_dummy_accounts_never_block_a_real_student(self):
        from ..student_views import student_number_taken
        learner("dummy@ue.edu.ph", number="2022606551")
        CustomUser.objects.filter(email="dummy@ue.edu.ph").update(is_dummy=True)
        self.assertFalse(student_number_taken("2022606551"))
        self.assertTrue(student_number_taken("2022606551", dummy=True))


class RegisterStudentNumberTests(TestCase):
    def test_a_student_number_registers_only_once(self):
        learner("first@ue.edu.ph", number="2022606551")
        r = self.client.post(reverse("register") + "?as=student", {
            "as": "student", "first_name": "Ana", "last_name": "Reyes", "email": "ana@ue.edu.ph",
            "password": "longenough1", "password2": "longenough1", "student_number": " 2022606551 ",
            "course": "BSIT", "year_level": "1", "section": "TN11", "consent": "on"})
        self.assertContains(r, "Another account already uses this student number")
        self.assertFalse(CustomUser.objects.filter(email="ana@ue.edu.ph").exists())
