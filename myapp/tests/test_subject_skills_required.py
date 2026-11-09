"""Every subject picked on a skill/subject survey (faculty, student, alumni) needs at least
one skill, and the onboarding tour's "tick a subject" step lights every semester's list
plus the subject search, not just this semester's."""
import json
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from ..models import CurriculumSurveyResponse, CustomUser
from .helpers import login_administrator

PY = [{"name": "Python", "level": "introduced"}]
STATIC = Path(settings.BASE_DIR) / "myapp" / "static" / "myapp"


class SubjectsNeedASkillTests(TestCase):
    def student_payload(self, skills):
        from .. import curriculum_data
        y1 = curriculum_data.build_student_eligibility()["BSIT"]["1"]
        return {"consent": True, "has_previous": False,
                "personal_info": {"name": "S", "ue_email": "s@ue.edu.ph", "course": "BSIT", "student_number": "1",
                                  "year_level": 1, "section": "A"},
                "subjects": [{"code": y1["current"]["subjects"][0]["code"], "term": "current", "skills": skills}]}

    def alumni_payload(self, skills):
        from .. import curriculum_data
        last = curriculum_data.learner_subjects_for_term("BSIT", curriculum_data.term_sequence("BSIT")[-1]["key"])[0]
        return {"consent": True,
                "personal_info": {"name": "A", "ue_email": "a@ue.edu.ph", "course": "BSIT", "student_number": "1",
                                  "year_graduated": "2025"},
                "subjects": [{"code": last["code"], "skills": PY}, {"code": "CIT 4199", "name": "Game Development",
                                                                    "custom": True, "skills": skills}],
                "employment": {"status": "unemployed"}}

    def post(self, name, payload):
        return self.client.post(reverse(name), content_type="application/json", data=json.dumps(payload))

    def test_student_subject_without_a_skill_is_refused(self):
        login_administrator(self.client)
        for skills in ([], None, [{"name": "  ", "level": "introduced"}]):
            r = self.post("student_survey_submit", self.student_payload(skills))
            self.assertEqual(r.status_code, 400)
            self.assertIn("at least one skill", r.json()["error"])
        self.assertFalse(CurriculumSurveyResponse.objects.exists())
        self.assertEqual(self.post("student_survey_submit", self.student_payload(PY)).status_code, 200)

    def test_alumni_subject_without_a_skill_is_refused(self):
        login_administrator(self.client)
        r = self.post("alumni_survey_submit", self.alumni_payload([]))
        self.assertEqual(r.status_code, 400)
        self.assertIn("CIT 4199", r.json()["error"])
        self.assertEqual(self.post("alumni_survey_submit", self.alumni_payload(PY)).status_code, 200)

    def test_professor_subject_without_a_skill_is_refused(self):
        prof = CustomUser.objects.create_user(email="prof@ue.edu.ph", password="x" * 12, first_name="P",
                                              last_name="Q", role="faculty")
        self.client.force_login(prof)
        payload = {"consent": True, "subjects": [{"code": "CFD 1101", "skills": PY}, {"code": "CCP 1101", "skills": []}]}
        r = self.post("professor_survey_submit", payload)
        self.assertEqual(r.status_code, 400)
        self.assertIn("CCP 1101", r.json()["error"])
        self.assertFalse(CurriculumSurveyResponse.objects.exists())
        payload["subjects"][1]["skills"] = PY
        self.assertEqual(self.post("professor_survey_submit", payload).status_code, 200)

    def test_pages_check_before_sending(self):
        self.assertIn("function missingSkillsError", (STATIC / "curriculum-survey.js").read_text(encoding="utf-8"))
        for name in ("cs-professor.js", "cs-student.js", "cs-alumni.js"):
            self.assertIn("CS.missingSkillsError(blocksWrap)", (STATIC / name).read_text(encoding="utf-8"), name)


class TourLightsEverySemesterTests(TestCase):
    def test_subject_lists_and_search_share_one_box(self):
        prof = CustomUser.objects.create_user(email="prof@ue.edu.ph", password="x" * 12, first_name="P",
                                              last_name="Q", role="faculty")
        self.client.force_login(prof)
        html = self.client.get(reverse("professor_survey")).content.decode()
        box = html.split('id="professor-subject-picker"', 1)[1].split('<h3>Subjects not in the list</h3>', 1)[0]
        for part in ('id="professor-subject-filter"', 'id="professor-current-subjects"', 'id="professor-previous-subjects"'):
            self.assertIn(part, box)
        login_administrator(self.client)
        html = self.client.get(reverse("student_survey")).content.decode()
        box = html.split('id="student-subject-picker"', 1)[1].split('<h3>Subjects not in the list</h3>', 1)[0]
        for part in ('id="student-subject-filter"', 'id="student-current-subjects"', 'id="student-previous-subjects"',
                     'id="student-earlier-subjects"'):
            self.assertIn(part, box)

    def test_tour_step_lights_the_whole_picker(self):
        js = (STATIC / "onboarding-tour.js").read_text(encoding="utf-8")
        self.assertIn("'#' + p + '-subject-picker'", js)
        self.assertIn("sel: [pickerSel, gridSel + ' .cs-subject-grid', gridSel]", js)
