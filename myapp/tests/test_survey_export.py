import csv
import io

from django.test import TestCase
from django.urls import reverse

from ..models import CurriculumSurveyResponse as C, CustomUser, SurveyResponse


def read_csv(resp):
    text = b"".join(resp.streaming_content).decode("utf-8") if resp.streaming else resp.content.decode("utf-8")
    assert text.startswith("﻿")
    return list(csv.DictReader(io.StringIO(text[1:])))


class SurveyExportTests(TestCase):
    def setUp(self):
        mk = lambda email, role: CustomUser.objects.create_user(email=email, password="secret123", first_name=email[:3],
                                                                 last_name="L", role=role)
        self.admin = mk("adm@ue.edu.ph", CustomUser.Role.ADMINISTRATOR)
        self.faculty = mk("fac@ue.edu.ph", CustomUser.Role.FACULTY)
        info = {"name": "Juan Cruz", "ue_email": "juan@ue.edu.ph", "course": "BSIT", "student_number": "2023-9",
                "year_level": 2, "section": "A"}
        self.juan = C.objects.create(respondent_type="student", data={
            "consent": True, "personal_info": info, "target_role": "",
            "subjects": [{"code": "CCP 1101", "term": "current", "skills": [
                {"name": "Python", "level": "advanced"}, {"name": "=HYPERLINK(1)", "level": "beginner"}]},
                {"code": "CFD 1101", "skills": []}]})
        self.maria = C.objects.create(respondent_type="alumni", data={
            "personal_info": {"name": "María Santos", "ue_email": "m@x.com", "course": "BSCS", "year_graduated": 2024},
            "employment": {"status": "employed", "job_title": "Dev"},
            "subjects": [{"code": "CFD 1101", "skills": [{"name": "SQL", "level": "applied"}]}]})
        C.objects.create(respondent_type="student", is_dummy=True,
                         data={"personal_info": {"name": "Test Kid"}, "subjects": []})
        C.objects.create(respondent_type="professor", user=self.faculty,
                         data={"subjects": [{"code": "CCP 1101", "skills": [{"name": "Java", "level": "applied"}]}]})
        SurveyResponse.objects.create(survey_type="sus", user=self.faculty, data={
            "q2": 4, "q10": 3, "q1": 5, "sus_score": 80.0, "sus_version": 5, "respondent_name": "Fac L"})
        SurveyResponse.objects.create(survey_type="sus", user=self.faculty, is_dummy=True, data={"q1": 1})
        SurveyResponse.objects.create(survey_type="functional", user=self.faculty, data={
            "test_case_id": "TC-1", "submission_id": "abc", "result": "Pass"})

    def test_admin_only(self):
        self.client.force_login(self.faculty)
        self.assertEqual(self.client.get(reverse("survey_responses_csv")).status_code, 403)
        self.assertEqual(self.client.get(reverse("feedback_responses_csv", args=["sus"])).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("survey_responses_csv")).status_code, 302)

    def test_curriculum_csv_one_row_per_skill(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("survey_responses_csv"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment;", r["Content-Disposition"])
        self.assertTrue(r["Content-Type"].startswith("text/csv"))
        rows = read_csv(r)
        juan = [x for x in rows if x["Name"] == "Juan Cruz"]
        self.assertEqual([x["Skill"] for x in juan], ["Python", "'=HYPERLINK(1)", ""])   # subject with no skills kept
        self.assertEqual(juan[0]["Student number"], "2023-9")
        self.assertEqual(juan[0]["Section"], "A")
        self.assertEqual(juan[0]["Subject code"], "CCP 1101")
        maria = [x for x in rows if x["Name"] == "María Santos"][0]
        self.assertEqual(maria["Employment: job_title"], "Dev")
        self.assertEqual(maria["Year graduated"], "2024")
        self.assertEqual(maria["Respondent type"], "Fresh Graduate / Alumni")
        prof = [x for x in rows if x["Account email"] == "fac@ue.edu.ph"][0]
        self.assertEqual(prof["Email"], "fac@ue.edu.ph")
        self.assertEqual(prof["Skill"], "Java")
        self.assertNotIn("Test Kid", {x["Name"] for x in rows})   # real answers by default

    def test_curriculum_csv_follows_filters(self):
        self.client.force_login(self.admin)
        rows = read_csv(self.client.get(reverse("survey_responses_csv"), {"type": "alumni"}))
        self.assertEqual({x["Name"] for x in rows}, {"María Santos"})
        rows = read_csv(self.client.get(reverse("survey_responses_csv"), {"q": "python"}))
        self.assertEqual({x["Name"] for x in rows}, {"Juan Cruz"})
        rows = read_csv(self.client.get(reverse("survey_responses_csv"), {"set": "dummy"}))
        self.assertEqual([x["Name"] for x in rows], ["Test Kid"])
        self.assertEqual(rows[0]["Data set"], "Dummy")

    def test_feedback_csv(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("feedback_responses_csv", args=["sus"]))
        self.assertEqual(r.status_code, 200)
        text = r.content.decode("utf-8")
        header = next(csv.reader(io.StringIO(text[1:])))
        self.assertEqual(header[5:], ["respondent_name", "sus_version", "q1", "q2", "q10", "sus_score"])
        rows = read_csv(r)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sus_score"], "80.0")
        self.assertEqual(rows[0]["Account email"], "fac@ue.edu.ph")
        rows = read_csv(self.client.get(reverse("feedback_responses_csv", args=["sus"]), {"set": "all"}))
        self.assertEqual(len(rows), 2)
        rows = read_csv(self.client.get(reverse("feedback_responses_csv", args=["functional"])))
        self.assertEqual(rows[0]["test_case_id"], "TC-1")
        self.assertEqual(self.client.get(reverse("feedback_responses_csv", args=["nope"])).status_code, 404)

    def test_page_has_download_links(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("survey_responses"), {"type": "student"})
        self.assertContains(r, reverse("survey_responses_csv") + "?type=student")
        self.assertContains(r, reverse("feedback_responses_csv", args=["sus"]) + "?set=real")
        self.assertContains(r, reverse("feedback_responses_csv", args=["functional"]))
