import json

from django.test import TestCase
from django.urls import reverse

from .models import CustomUser, SurveyResponse


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