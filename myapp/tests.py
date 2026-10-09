import json

from django.test import TestCase
from django.urls import reverse

from .models import CustomUser, SurveyResponse, DEFAULT_PASSWORD


class SurveyAndLogoutTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="jose.rizal@ue.edu.ph", password="rizal123",
            first_name="Jose", last_name="Rizal",
        )
        self.url = reverse("survey_submit")

    def post(self, payload):
        return self.client.post(self.url, data=json.dumps(payload), content_type="application/json")

    def sus_row(self, value=5):
        row = {f"q{n}": value for n in range(1, 11)}
        row.update({"respondent_role": "Student", "program": "BSIT", "sus_score": 999, "comments": None})
        return row

    def test_requires_login(self):
        resp = self.post({"type": "sus", "rows": [self.sus_row()]})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(SurveyResponse.objects.count(), 0)

    def test_sus_saved_and_score_recomputed_on_server(self):
        self.client.force_login(self.user)
        # all 5s: odd items give 4 each (5 x 4 = 20), even items give 0 -> 20 x 2.5 = 50
        resp = self.post({"type": "sus", "rows": [self.sus_row(5)]})
        self.assertEqual(resp.status_code, 200)
        saved = SurveyResponse.objects.get()
        self.assertEqual(saved.user, self.user)
        self.assertEqual(saved.data["sus_score"], 50.0)  # client's 999 is ignored

    def test_sus_rejects_out_of_range_answer(self):
        self.client.force_login(self.user)
        row = self.sus_row(); row["q3"] = 9
        self.assertEqual(self.post({"type": "sus", "rows": [row]}).status_code, 400)
        self.assertEqual(SurveyResponse.objects.count(), 0)

    def test_functional_saves_one_row_per_test_case(self):
        self.client.force_login(self.user)
        rows = [{"submission_id": "abc", "test_case_id": f"TC-0{i}", "status": "Pass"} for i in (1, 2, 3)]
        self.assertEqual(self.post({"type": "functional", "rows": rows}).status_code, 200)
        self.assertEqual(SurveyResponse.objects.filter(survey_type="functional").count(), 3)

    def test_rejects_bad_type_and_bad_json_and_get(self):
        self.client.force_login(self.user)
        self.assertEqual(self.post({"type": "nope", "rows": [{}]}).status_code, 400)
        self.assertEqual(self.client.post(self.url, data="not json", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_logout_ends_session(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.assertRedirects(self.client.get(reverse("logout")), reverse("login"))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)  # login_required kicks in

    def test_feedback_page_points_survey_js_at_submit_url(self):
        self.client.force_login(self.user)
        html = self.client.get(reverse("feedback")).content.decode()
        self.assertIn(f'data-submit-url="{self.url}"', html)

class RoleAndPasswordTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            "admin@ue.edu.ph", "adminpass1", first_name="Ada", last_name="Min",
            role=CustomUser.Role.ADMINISTRATOR)
        self.faculty = CustomUser.objects.create_user(
            "fac@ue.edu.ph", "facpass123", first_name="Fay", last_name="Culty")

    # --- role
    def test_default_role_is_faculty(self):
        self.assertEqual(self.faculty.role, "faculty")
        self.assertFalse(self.faculty.is_administrator)
        self.assertTrue(self.admin.is_administrator)

    def test_superuser_is_administrator(self):
        su = CustomUser.objects.create_superuser("su@ue.edu.ph", "superpass1", first_name="S", last_name="U")
        self.assertTrue(su.is_administrator)

    def test_signup_always_faculty_and_min_length(self):
        r = self.client.post(reverse("signup"), {"last_name": "A", "first_name": "B", "email": "x@ue.edu.ph",
                                                  "password": "short", "password2": "short"})
        self.assertContains(r, "at least 8")
        self.assertFalse(CustomUser.objects.filter(email="x@ue.edu.ph").exists())
        self.client.post(reverse("signup"), {"last_name": "A", "first_name": "B", "email": "x@ue.edu.ph",
                                              "password": "longenough1", "password2": "longenough1", "role": "administrator"})
        self.assertEqual(CustomUser.objects.get(email="x@ue.edu.ph").role, "faculty")

    # --- change password
    def test_change_password(self):
        self.client.force_login(self.faculty)
        url = reverse("change_password")
        post = lambda c, n, f: self.client.post(url, {"current_password": c, "new_password": n, "confirm_password": f}, follow=True)

        self.assertContains(post("wrong", "newpass123", "newpass123"), "Current password is incorrect")
        self.assertContains(post("facpass123", "short", "short"), "at least 8")
        self.assertContains(post("facpass123", "newpass123", "different1"), "do not match")
        self.faculty.refresh_from_db()
        self.assertTrue(self.faculty.check_password("facpass123"))

        r = post("facpass123", "newpass123", "newpass123")
        self.assertContains(r, "has been changed")
        self.faculty.refresh_from_db()
        self.assertTrue(self.faculty.check_password("newpass123"))
        # still logged in afterwards
        self.assertEqual(self.client.get(reverse("settings")).status_code, 200)

    def test_change_password_requires_login(self):
        r = self.client.post(reverse("change_password"), {})
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("login"), r["Location"])


class AccountsPageTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            "admin@ue.edu.ph", "adminpass1", first_name="Ada", last_name="Min",
            role=CustomUser.Role.ADMINISTRATOR)
        self.faculty = CustomUser.objects.create_user(
            "fac@ue.edu.ph", "facpass123", first_name="Fay", last_name="Culty")

    def test_sidebar_link_only_for_admin(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("dashboard")), reverse("accounts"))
        self.client.force_login(self.faculty)
        self.assertNotContains(self.client.get(reverse("dashboard")), reverse("accounts"))

    def test_faculty_blocked_everywhere(self):
        self.client.force_login(self.faculty)
        self.assertEqual(self.client.get(reverse("accounts")).status_code, 403)
        for name, args in [("account_create", []), ("account_edit", [self.admin.pk]),
                           ("account_reset_password", [self.admin.pk]), ("account_delete", [self.admin.pk])]:
            self.assertEqual(self.client.post(reverse(name, args=args), {"email": "z@ue.edu.ph"}).status_code, 403, name)
        self.assertTrue(CustomUser.objects.filter(pk=self.admin.pk).exists())

    def test_anonymous_redirected(self):
        self.assertEqual(self.client.get(reverse("accounts")).status_code, 302)

    def test_create(self):
        self.client.force_login(self.admin)
        url = reverse("account_create")
        base = {"last_name": "Cruz", "first_name": "Juan", "email": "juan@ue.edu.ph", "role": "faculty"}
        self.client.post(url, base)
        u = CustomUser.objects.get(email="juan@ue.edu.ph")
        self.assertTrue(u.check_password(DEFAULT_PASSWORD))
        self.assertEqual(u.role, "faculty")
        # duplicate email (case-insensitive), bad role, short password
        self.client.post(url, {**base, "email": "JUAN@ue.edu.ph"})
        self.client.post(url, {**base, "email": "b@ue.edu.ph", "role": "root"})
        self.client.post(url, {**base, "email": "c@ue.edu.ph", "password": "short"})
        self.assertEqual(CustomUser.objects.filter(email__iexact="juan@ue.edu.ph").count(), 1)
        self.assertFalse(CustomUser.objects.filter(email__in=["b@ue.edu.ph", "c@ue.edu.ph"]).exists())
        self.client.post(url, {**base, "email": "boss@ue.edu.ph", "role": "administrator", "password": "mypassword1"})
        boss = CustomUser.objects.get(email="boss@ue.edu.ph")
        self.assertTrue(boss.is_administrator)
        self.assertTrue(boss.check_password("mypassword1"))

    def test_edit_name_and_email(self):
        self.client.force_login(self.admin)
        url = reverse("account_edit", args=[self.faculty.pk])
        self.client.post(url, {"last_name": "New", "first_name": "Name", "middle_name": "M", "email": "new@ue.edu.ph"})
        self.faculty.refresh_from_db()
        self.assertEqual(self.faculty.get_full_name(), "Name M New")
        self.assertEqual(self.faculty.email, "new@ue.edu.ph")
        self.assertEqual(self.faculty.role, "faculty")  # edit can't change role
        # email already used by someone else
        self.client.post(url, {"last_name": "New", "first_name": "Name", "email": "admin@ue.edu.ph"})
        self.faculty.refresh_from_db()
        self.assertEqual(self.faculty.email, "new@ue.edu.ph")

    def test_reset_password(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("account_reset_password", args=[self.faculty.pk]))
        self.faculty.refresh_from_db()
        self.assertTrue(self.faculty.check_password(DEFAULT_PASSWORD))

    def test_reset_own_password_keeps_session(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("account_reset_password", args=[self.admin.pk]))
        self.assertEqual(self.client.get(reverse("accounts")).status_code, 200)

    def test_delete(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("account_delete", args=[self.faculty.pk]))
        self.assertFalse(CustomUser.objects.filter(pk=self.faculty.pk).exists())
        # cannot delete self
        self.client.post(reverse("account_delete", args=[self.admin.pk]))
        self.assertTrue(CustomUser.objects.filter(pk=self.admin.pk).exists())

    def test_get_not_allowed_on_actions(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("account_delete", args=[self.faculty.pk])).status_code, 405)
