"""Curriculum survey pages:
* R1  a student / alumni / faculty member who hasn't answered their initial survey gets the
      "answer the initial survey first" pop-up (survey-first.js + its allow-list); the
      middleware redirect stays as a fallback and adds ?required=1.
* R2  saved answers open read-only with an "Edit" button (My subjects & skills, Professor Survey);
      a first answer still says "Submit survey".
* R3  a "Clear all answers" button on the student, alumni and professor surveys and on
      My subjects & skills (shown while editing)."""
import json
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import CurriculumSurveyResponse, CustomUser
from .helpers import IsolatedDataMixin

STATIC = Path(__file__).resolve().parent.parent / "static" / "myapp"


def survey_first_cfg(html):
    marker = '<script id="survey-first" type="application/json">'
    if marker not in html:
        return None
    start = html.index(marker) + len(marker)
    return json.loads(html[start:html.index("</script>", start)])


@override_settings(REQUIRE_PROFESSOR_SURVEY=True, REQUIRE_LEARNER_SURVEY=True)
class SurveyFirstPopupTests(IsolatedDataMixin, TestCase):
    def make(self, role, **extra):
        return CustomUser.objects.create_user(email=f"{role}{len(extra)}@ue.edu.ph", password="x" * 12,
                                              first_name="A", last_name="B", role=role, **extra)

    def test_faculty_without_survey_get_the_popup_config(self):
        self.client.force_login(self.make("faculty"))
        r = self.client.get(reverse("professor_survey") + "?first=1&required=1")
        cfg = survey_first_cfg(r.content.decode())
        self.assertEqual(cfg["url"], reverse("professor_survey"))
        for name in ("logout", "settings", "help", "about", "professor_survey"):
            self.assertIn(reverse(name), cfg["allowed"])
        for name in ("dashboard", "recommendations", "data", "feedback"):
            self.assertNotIn(reverse(name), cfg["allowed"])
        self.assertContains(r, "survey-first.js")
        self.assertContains(r, "ue-modal.js")
        # Settings (allowed) carries it too, so its sidebar links are covered
        self.assertIsNotNone(survey_first_cfg(self.client.get(reverse("settings")).content.decode()))

    def test_learners_without_survey_get_their_own_survey_url(self):
        self.client.force_login(self.make("alumni"))
        r = self.client.get(reverse("student_dashboard"))
        self.assertRedirects(r, reverse("alumni_survey") + "?required=1", fetch_redirect_response=False)
        cfg = survey_first_cfg(self.client.get(reverse("alumni_survey") + "?required=1").content.decode())
        self.assertEqual(cfg["url"], reverse("alumni_survey"))
        self.assertIn(reverse("logout"), cfg["allowed"])
        self.assertNotIn(reverse("student_dashboard"), cfg["allowed"])

    def test_no_popup_once_answered_or_for_staff(self):
        prof = self.make("faculty")
        CurriculumSurveyResponse.objects.create(respondent_type="professor", user=prof, data={})
        self.client.force_login(prof)
        self.assertIsNone(survey_first_cfg(self.client.get(reverse("settings")).content.decode()))
        for role in ("administrator", "developer"):
            self.client.force_login(self.make(role))
            self.assertIsNone(survey_first_cfg(self.client.get(reverse("settings")).content.decode()))
        self.client.force_login(self.make("student", is_dummy=True))
        self.assertIsNone(survey_first_cfg(self.client.get(reverse("settings")).content.decode()))

    def test_popup_wording(self):
        js = (STATIC / "survey-first.js").read_text(encoding="utf-8")
        self.assertIn("Please answer the initial survey first.", js)
        self.assertIn("UEnvision needs your answers before it can show your results.", js)
        self.assertIn("'Go to survey'", js)
        self.assertIn("'Close'", js)
        self.assertIn("hideOk: onSurvey", js)   # on the survey itself only Close is shown


@override_settings(REQUIRE_PROFESSOR_SURVEY=True, REQUIRE_LEARNER_SURVEY=True)
class EditButtonAndClearAllTests(IsolatedDataMixin, TestCase):
    def test_my_skills_opens_read_only_with_edit(self):
        user = CustomUser.objects.create_user(email="s@ue.edu.ph", password="x" * 12, first_name="S",
                                              last_name="T", role=CustomUser.Role.STUDENT)
        CurriculumSurveyResponse.objects.create(respondent_type="student", user=user, data={
            "personal_info": {"course": "BSIT"},
            "subjects": [{"code": "CCP 1101", "skills": [{"name": "Python", "level": "applied"}]}]})
        self.client.force_login(user)
        r = self.client.get(reverse("my_skills"))
        self.assertContains(r, 'class="ms-form is-readonly"')
        self.assertContains(r, 'id="ms-edit"')
        self.assertContains(r, 'id="ms-cancel" data-ms-action hidden>Cancel</button>')
        self.assertContains(r, 'id="ms-save" data-ms-action hidden>Save changes</button>')
        self.assertContains(r, 'id="ms-clear" data-ms-action hidden>Clear all answers</button>')

    def test_professor_survey_read_only_after_first_answer(self):
        prof = CustomUser.objects.create_user(email="p@ue.edu.ph", password="x" * 12, first_name="P",
                                              last_name="R", role=CustomUser.Role.FACULTY)
        self.client.force_login(prof)
        first = self.client.get(reverse("professor_survey"))
        self.assertContains(first, ">Submit survey</button>")
        self.assertNotContains(first, 'id="professor-edit"')
        self.assertContains(first, 'id="professor-clear" data-ps-action>Clear all answers</button>')
        self.assertNotContains(first, "cs-panel is-readonly")
        CurriculumSurveyResponse.objects.create(respondent_type="professor", user=prof, data={
            "consent": True, "subjects": [{"code": "CCP 1101", "skills": [{"name": "Python", "level": "applied"}]}]})
        again = self.client.get(reverse("professor_survey"))
        self.assertContains(again, "cs-panel is-readonly")
        self.assertContains(again, 'id="professor-edit"')
        self.assertContains(again, 'id="professor-save" data-ps-action hidden>Save changes</button>')
        self.assertContains(again, 'id="professor-cancel" data-ps-action hidden>Cancel</button>')

    def test_learner_surveys_have_clear_all(self):
        for kind in ("student", "alumni"):
            user = CustomUser.objects.create_user(email=f"{kind}@ue.edu.ph", password="x" * 12, first_name="A",
                                                  last_name="B", role=kind)
            self.client.force_login(user)
            r = self.client.get(reverse(f"{kind}_survey"))
            self.assertContains(r, f'id="{kind}-clear">Clear all answers</button>')
            self.assertContains(r, ">Submit survey</button>")

    def test_scripts_use_the_on_page_dialog_not_confirm(self):
        for name in ("cs-professor.js", "cs-my-skills.js", "cs-student.js", "cs-alumni.js",
                     "curriculum-survey.js", "survey.js", "survey-first.js"):
            js = (STATIC / name).read_text(encoding="utf-8")
            self.assertNotIn("window.confirm(", js, name)
            self.assertNotIn("alert(", js, name)
        js = (STATIC / "curriculum-survey.js").read_text(encoding="utf-8")
        self.assertIn("Clear all your answers on this page? Nothing is saved until you submit.", js)
        self.assertIn("wireClearAll", (STATIC / "cs-student.js").read_text(encoding="utf-8"))
        self.assertIn("wireClearAll", (STATIC / "cs-alumni.js").read_text(encoding="utf-8"))
        self.assertIn("wireClearAll", (STATIC / "cs-professor.js").read_text(encoding="utf-8"))
        # the unsaved-changes warning still works while editing
        self.assertIn("beforeunload", (STATIC / "cs-my-skills.js").read_text(encoding="utf-8"))
        self.assertIn("beforeunload", (STATIC / "cs-professor.js").read_text(encoding="utf-8"))
