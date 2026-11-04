"""Feedback page: answered surveys show their saved answers and can be edited.
Saving again replaces the account's earlier answer (same survey and version) instead of
adding another row; older duplicate rows from before this change are left alone."""
import json
from pathlib import Path

from django.test import TestCase
from django.urls import reverse

from ..models import CustomUser, SurveyResponse


def sus_row(value=5, comments=None):
    row = {f"q{n}": value for n in range(1, 7)}
    row["comments"] = comments
    return row


def uat_row(value=4):
    return {f"q{n}": value for n in range(1, 11)}


class FeedbackEditTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(email="ana@ue.edu.ph", password="x" * 12,
                                                   first_name="Ana", last_name="Reyes", role="faculty")
        self.client.force_login(self.user)
        self.url = reverse("survey_submit")

    def post(self, payload):
        return self.client.post(self.url, data=json.dumps(payload), content_type="application/json")

    def saved_on_page(self):
        html = self.client.get(reverse("feedback")).content.decode()
        start = html.index('<script id="saved-feedback" type="application/json">') + len('<script id="saved-feedback" type="application/json">')
        return json.loads(html[start:html.index("</script>", start)]), html

    def test_second_sus_submission_replaces_the_first(self):
        self.assertEqual(self.post({"type": "sus", "rows": [sus_row(5)]}).json()["edited"], False)
        resp = self.post({"type": "sus", "rows": [sus_row(3, "better now")]})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["edited"])
        self.assertEqual(SurveyResponse.objects.filter(survey_type="sus").count(), 1)
        row = SurveyResponse.objects.get(survey_type="sus")
        self.assertEqual((row.data["sus_score"], row.data["comments"]), (50.0, "better now"))
        self.assertTrue(row.data["edited_at"])
        self.assertEqual(resp.json()["answers"]["q1"], 3)

    def test_uat_is_replaced_too_and_other_users_are_untouched(self):
        other = CustomUser.objects.create_user(email="ben@ue.edu.ph", password="x" * 12, first_name="Ben",
                                               last_name="Cruz", role="faculty")
        SurveyResponse.objects.create(survey_type="uat", user=other, data={**uat_row(2), "uat_version": 2})
        self.post({"type": "uat", "rows": [uat_row(4)]})
        self.post({"type": "uat", "rows": [uat_row(5)]})
        self.assertEqual(SurveyResponse.objects.filter(survey_type="uat", user=self.user).count(), 1)
        self.assertEqual(SurveyResponse.objects.get(survey_type="uat", user=self.user).data["uat_score"], 5.0)
        self.assertEqual(SurveyResponse.objects.get(survey_type="uat", user=other).data["q1"], 2)

    def test_existing_duplicates_are_kept_and_the_latest_is_edited(self):
        a = SurveyResponse.objects.create(survey_type="sus", user=self.user, data={**sus_row(1), "sus_version": 5})
        b = SurveyResponse.objects.create(survey_type="sus", user=self.user, data={**sus_row(2), "sus_version": 5})
        saved, _ = self.saved_on_page()
        self.assertEqual(saved["sus"]["q1"], 2)   # the latest one is shown
        self.post({"type": "sus", "rows": [sus_row(4)]})
        self.assertEqual(SurveyResponse.objects.filter(survey_type="sus").count(), 2)   # nothing deleted or added
        a.refresh_from_db(); b.refresh_from_db()
        self.assertEqual((a.data["q1"], b.data["q1"]), (1, 4))

    def test_an_answer_to_an_older_version_is_not_overwritten(self):
        old = SurveyResponse.objects.create(survey_type="sus", user=self.user, data={**sus_row(1), "sus_version": 4})
        self.post({"type": "sus", "rows": [sus_row(5)]})
        self.assertEqual(SurveyResponse.objects.filter(survey_type="sus").count(), 2)
        old.refresh_from_db()
        self.assertEqual(old.data["q1"], 1)

    def test_functional_sheet_edit_replaces_the_latest_sheet(self):
        first = [{"submission_id": "abc", "test_case_id": f"TC-0{i}", "feature": "F", "scenario": "S",
                  "status": "Yes"} for i in (1, 2, 3)]
        self.post({"type": "functional", "rows": first})
        again = [{"submission_id": "new-id", "test_case_id": f"TC-0{i}", "feature": "F", "scenario": "S",
                  "status": "No", "actual_result": "broke"} for i in (1, 2)]
        resp = self.post({"type": "functional", "rows": again})
        self.assertTrue(resp.json()["edited"])
        rows = SurveyResponse.objects.filter(survey_type="functional")
        self.assertEqual(rows.count(), 2)
        self.assertEqual({r.data["submission_id"] for r in rows}, {"abc"})   # same sheet, kept its id
        self.assertEqual({r.data["status"] for r in rows}, {"No"})

    def test_page_shows_saved_answers_with_edit_button(self):
        saved, html = self.saved_on_page()
        self.assertEqual(saved, {})
        self.post({"type": "sus", "rows": [sus_row(4, "nice")]})
        saved, html = self.saved_on_page()
        self.assertEqual((saved["sus"]["q1"], saved["sus"]["comments"]), (4, "nice"))
        self.assertTrue(saved["sus"]["submitted_at"])
        self.assertNotIn("uat", saved)
        self.assertIn('data-edit="sus"', html)
        self.assertIn("Edit answers", html)
        self.assertIn("Answered · edit", html)

    def test_sus_and_uat_take_one_answer_at_a_time(self):
        self.assertEqual(self.post({"type": "sus", "rows": [sus_row(), sus_row()]}).status_code, 400)
        self.assertEqual(SurveyResponse.objects.count(), 0)

    def test_survey_tracker_counts_one_response_per_user(self):
        from ..survey_tracker import tracker_rows
        for v in (3, 4, 5):
            self.post({"type": "sus", "rows": [sus_row(v)]})
        self.assertEqual(SurveyResponse.objects.filter(user=self.user, survey_type="sus").count(), 1)
        row = tracker_rows([self.user])[0]
        self.assertIs(row["cells"]["sus"], True)
        self.assertIs(row["cells"]["uat"], False)

    def test_likert_labels_every_point(self):
        js = (Path(__file__).resolve().parent.parent / "static" / "myapp" / "survey.js").read_text(encoding="utf-8")
        self.assertIn("['Strongly disagree', 'Disagree', 'Neutral', 'Agree', 'Strongly agree']", js)
        self.assertIn('likert-label', js)
        self.assertNotIn('likert-end', js)
