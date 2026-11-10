"""Alumni don't have to give a student number (students still do), and the new logo is on the pages."""
import json

from django.test import TestCase
from django.urls import reverse

from ..models import CustomUser
from .helpers import IsolatedDataMixin
from .test_about_you import learner


class AlumniStudentNumberOptionalTests(IsolatedDataMixin, TestCase):
    def register(self, kind, **over):
        data = {"first_name": "Ana", "last_name": "Reyes", "email": f"ana.{kind}@gmail.com", "course": "BSCS",
                "student_number": "", "year_graduated": "2024", "year_level": "1", "section": "TN11",
                "password": "secret12345", "password2": "secret12345", "consent": "on", **over}
        return self.client.post(reverse("register") + f"?as={kind}", data)

    def test_alumni_register_without_a_student_number(self):
        r = self.register("alumni")
        self.assertNotContains(r, "Please enter your student number", status_code=r.status_code)
        user = CustomUser.objects.get(email="ana.alumni@gmail.com")
        self.assertEqual(user.learner_info["student_number"], "")
        # a second alumni without one is not "already using this student number"
        self.client.logout()
        self.register("alumni", email="ben@gmail.com", first_name="Ben")
        self.assertTrue(CustomUser.objects.filter(email="ben@gmail.com").exists())

    def test_students_still_need_one(self):
        r = self.register("student")
        self.assertContains(r, "Please enter your student number.")
        self.assertFalse(CustomUser.objects.filter(email="ana.student@gmail.com").exists())

    def test_the_forms_mark_it_optional_for_alumni_only(self):
        page = self.client.get(reverse("register") + "?as=alumni").content.decode()
        field = page.split('name="student_number"')[1].split(">")[0]
        self.assertNotIn("required", field)
        self.assertIn("(optional)", page.split('name="student_number"')[0][-120:])
        page = self.client.get(reverse("register") + "?as=student").content.decode()
        self.assertIn("required", page.split('name="student_number"')[1].split(">")[0])

    def test_about_you_saves_a_blank_number_and_the_survey_counts_the_account_as_complete(self):
        user = learner("al@gmail.com", CustomUser.Role.ALUMNI, number="")
        self.client.force_login(user)
        r = self.client.post(reverse("learner_about_save"), content_type="application/json", data=json.dumps(
            {"first_name": "Juan", "last_name": "Cruz", "course": "BSIT", "student_number": "", "year_graduated": "2025"}))
        self.assertEqual(r.status_code, 200, r.content)
        page = self.client.get(reverse("alumni_survey")).content.decode()
        self.assertIn('id="alumni-about"', page)                      # the short "About you" line, not the open form
        self.assertIn('data-about-optional="student_number" hidden', page)
        self.assertNotIn("required", page.split('id="alumni-number"')[1].split(">")[0])


class NewLogoTests(TestCase):
    def test_pages_use_the_new_logo_files(self):
        login = self.client.get(reverse("login")).content.decode()
        self.assertIn("img/logo/uenvision-vertical.svg", login)
        self.assertIn("img/logo/uenvision-vertical-dark.svg", login)     # shown instead in the dark theme
        self.assertIn("img/logo/uenvision-mark.svg", login)              # browser tab icon
        home = self.client.get(reverse("home")).content.decode()
        self.assertIn("img/logo/uenvision-horizontal.svg", home)
        for page in (login, home):
            self.assertNotIn("uenvision-logo.png", page)
            self.assertNotIn("uenvision-mark.png", page)
