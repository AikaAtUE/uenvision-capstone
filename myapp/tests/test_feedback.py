import json

from django.test import TestCase
from django.urls import reverse


from ..models import CustomUser, SurveyResponse


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
        row = {f"q{n}": value for n in range(1, 7)}
        row.update({"respondent_role": "Student", "sus_score": 999, "comments": None})
        return row

    def uat_row(self, value=4):
        return {f"q{n}": value for n in range(1, 11)}

    def test_uat_is_a_likert_satisfaction_survey(self):
        self.client.force_login(self.user)
        resp = self.post({"type": "uat", "rows": [self.uat_row(4)]})
        self.assertEqual(resp.status_code, 200)
        uat = SurveyResponse.objects.get(survey_type="uat")
        self.assertEqual((uat.data["uat_score"], uat.data["uat_version"]), (4.0, 2))
        bad = self.uat_row(); bad["q10"] = 6
        self.assertEqual(self.post({"type": "uat", "rows": [bad]}).status_code, 400)
        self.assertEqual(self.post({"type": "uat", "rows": [{"login_worked": "Yes"}]}).status_code, 400)

    def test_requires_login(self):
        resp = self.post({"type": "sus", "rows": [self.sus_row()]})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(SurveyResponse.objects.count(), 0)

    def test_sus_saved_and_score_recomputed_on_server(self):
        self.client.force_login(self.user)
        # all-positive SUS: every item gives (answer - 1); all 5s -> 100, all 3s -> 50
        resp = self.post({"type": "sus", "rows": [self.sus_row(5)]})
        self.assertEqual(resp.status_code, 200)
        saved = SurveyResponse.objects.get()
        self.assertEqual(saved.user, self.user)
        self.assertEqual(saved.data["sus_score"], 100.0)  # client's 999 is ignored
        self.assertEqual(saved.data["sus_version"], 5)
        self.assertEqual(saved.data["sus_audience"], "faculty")
        self.assertEqual(self.post({"type": "sus", "rows": [self.sus_row(3)]}).status_code, 200)
        self.assertEqual(SurveyResponse.objects.order_by("-pk").first().data["sus_score"], 50.0)

    def test_survey_js_asks_as_many_sus_questions_as_the_server_expects(self):
        import re
        from pathlib import Path
        from ..views import SUS_QUESTION_COUNT
        js = (Path(__file__).resolve().parent.parent / "static" / "myapp" / "survey.js").read_text(encoding="utf-8")
        block = re.search(r"var SUS_QUESTIONS = \[(.*?)\];", js, re.S).group(1)
        self.assertEqual(len(re.findall(r"^\s*'", block, re.M)), SUS_QUESTION_COUNT)

    def test_sus_first_statement_is_worded_for_the_role(self):
        from ..views import SUS_FIRST_STATEMENTS
        for role, audience in [(CustomUser.Role.STUDENT, "student"), (CustomUser.Role.ALUMNI, "alumni"),
                               (CustomUser.Role.FACULTY, "faculty"), (CustomUser.Role.ADMINISTRATOR, "faculty")]:
            user = CustomUser.objects.create_user(email=f"{role}@ue.edu.ph", password="secret123",
                                                  first_name="A", last_name="B", role=role)
            self.client.force_login(user)
            html = self.client.get(reverse("feedback")).content.decode()
            self.assertIn(f'data-first-statement="{SUS_FIRST_STATEMENTS[audience]}"', html)
            self.assertTrue(SUS_FIRST_STATEMENTS[audience].startswith("I would like to use UEnvision to "))
            self.post({"type": "sus", "rows": [self.sus_row()]})
            self.assertEqual(SurveyResponse.objects.filter(user=user).get().data["sus_audience"], audience)

    def test_name_and_role_come_from_the_account(self):
        self.client.force_login(self.user)
        row = self.sus_row()  # the form says "Student"; the account is Faculty
        self.post({"type": "sus", "rows": [row]})
        saved = SurveyResponse.objects.get()
        self.assertEqual(saved.data["respondent_role"], "Faculty")
        self.assertEqual(saved.data["respondent_name"], "Jose Rizal")
        self.post({"type": "uat", "rows": [{"tester_name": "Someone else", **self.uat_row()}]})
        uat = SurveyResponse.objects.get(survey_type="uat")
        self.assertEqual((uat.data["tester_name"], uat.data["tester_role"]), ("Jose Rizal", "Faculty"))

    def test_feedback_forms_do_not_ask_for_name_role_or_partial(self):
        self.client.force_login(self.user)
        html = self.client.get(reverse("feedback")).content.decode()
        for gone in ('id="sus-role"', 'id="uat-name"', 'id="uat-role"', 'id="uat-satisfaction"', 'id="functional-tester"'):
            self.assertNotIn(gone, html)
        self.assertIn("Answering as <strong>Jose Rizal</strong> (Faculty)", html)

    def test_uat_date_is_the_day_it_was_completed(self):
        from django.utils import timezone
        from ..views import PH_TIME
        self.client.force_login(self.user)
        self.post({"type": "uat", "rows": [{"test_date": "2001-01-01", **self.uat_row()}]})
        uat = SurveyResponse.objects.get(survey_type="uat")
        today = timezone.localdate(timezone=PH_TIME).isoformat()
        self.assertEqual(uat.data["test_date"], today)  # the form's date is ignored

    def test_feedback_forms_do_not_ask_for_program_or_test_date(self):
        self.client.force_login(self.user)
        html = self.client.get(reverse("feedback")).content.decode()
        for gone in ('id="sus-program"', 'id="uat-program"', 'id="uat-date"'):
            self.assertNotIn(gone, html)

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
        self.assertRedirects(self.client.get(reverse("logout")), reverse("home"))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)  # login_required kicks in

    def test_feedback_page_points_survey_js_at_submit_url(self):
        self.client.force_login(self.user)
        html = self.client.get(reverse("feedback")).content.decode()
        self.assertIn(f'data-submit-url="{self.url}"', html)


class HelpPageTests(TestCase):
    def page_for(self, role, **extra):
        user = CustomUser.objects.create_user(email=f"{role}@ue.edu.ph", password="x" * 12, first_name="A",
                                              last_name="B", role=role, **extra)
        self.client.force_login(user)
        return self.client.get(reverse("help"))

    def test_each_role_sees_its_own_steps(self):
        r = self.page_for("student")
        self.assertEqual(r.status_code, 200)  # students may open it
        self.assertContains(r, "Students and alumni")
        self.assertNotContains(r, "Administrators</h2>")
        r = self.page_for("faculty")
        self.assertContains(r, "Faculty</h2>")
        self.assertNotContains(r, "Students and alumni")
        r = self.page_for("administrator")
        self.assertContains(r, "Administrators</h2>")
        r = self.page_for("developer")
        for title in ("Students and alumni", "Faculty</h2>", "Administrators</h2>"):
            self.assertContains(r, title)

    def test_linked_from_the_sidebar(self):
        r = self.page_for("faculty")
        self.assertContains(r, f'href="{reverse("help")}"')


class FeedbackNudgeTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(email="fac@ue.edu.ph", password="x" * 12,
                                                   first_name="Ana", last_name="Reyes")
        self.client.force_login(self.user)

    def test_banner_shows_after_a_few_uses_until_answered(self):
        from ..feedback_nudge import USES_BEFORE_ASKING
        for _ in range(USES_BEFORE_ASKING - 1):
            self.client.get(reverse("dashboard"))
        self.assertNotContains(self.client.get(reverse("about")), "Help us evaluate UEnvision")
        self.client.get(reverse("dashboard"))
        page = self.client.get(reverse("about"))
        self.assertContains(page, "Help us evaluate UEnvision")
        self.assertContains(page, "SUS evaluation, UAT survey and test case sheet")
        self.assertContains(page, reverse("feedback") + "?survey=sus")
        self.assertNotContains(self.client.get(reverse("feedback")), "Help us evaluate UEnvision")
        for kind in ("sus", "uat", "functional"):
            SurveyResponse.objects.create(survey_type=kind, user=self.user, data={})
        self.assertNotContains(self.client.get(reverse("about")), "Help us evaluate UEnvision")

    def test_later_hides_it_for_a_few_days(self):
        CustomUser.objects.filter(pk=self.user.pk).update(app_uses=10)
        r = self.client.post(reverse("feedback_later"), {"next": reverse("about")})
        self.assertRedirects(r, reverse("about"))
        self.assertNotContains(self.client.get(reverse("about")), "Help us evaluate UEnvision")
        CustomUser.objects.filter(pk=self.user.pk).update(feedback_snoozed_until=None)
        self.assertContains(self.client.get(reverse("about")), "Help us evaluate UEnvision")

    def test_students_are_only_asked_for_the_sus(self):
        from ..feedback_nudge import missing_surveys
        student = CustomUser.objects.create_user(email="stu@ue.edu.ph", password="x" * 12, first_name="S",
                                                 last_name="T", role="student")
        self.assertEqual([k for k, _ in missing_surveys(student)], ["sus"])


class FunctionalSheetTests(TestCase):
    def js(self):
        from pathlib import Path
        return (Path(__file__).resolve().parent.parent / "static" / "myapp" / "survey.js").read_text(encoding="utf-8")

    def test_login_case_paragraph_scenarios_and_yes_no_answers(self):
        js = self.js()
        block = js[js.index("var FUNCTIONAL_DEFAULT_ROWS"):js.index("var functionalRowCount")]
        self.assertIn("feature: 'Login'", block)        # the login case is back, per the adviser
        self.assertNotIn("Log out", block)
        # one scenario paragraph per case, no separate steps / expected result
        self.assertIn("scenario:", block)
        self.assertNotIn("steps:", block)
        self.assertNotIn("expected:", block)
        self.assertIn("['Yes', 'No']", js)
        self.assertNotIn("Blocked", js)

    def test_uat_has_no_login_question(self):
        js = self.js()
        block = js[js.index("var UAT_QUESTIONS"):js.index("var FUNCTIONAL_DEFAULT_ROWS")]
        self.assertNotIn("Logging in", block)
        self.assertEqual(block.count("'") // 2, 10)    # ten Likert statements

    def test_sheet_explains_what_it_is_for(self):
        user = CustomUser.objects.create_user(email="f@ue.edu.ph", password="secret123", first_name="F", last_name="A")
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse("feedback")), "A functional test checks that each part of UEnvision")
