"""Second batch of system edits:
password reset (30 s resend, really sent), lockout (20 tries, 30 s), developer Alumni view,
ranked skill suggestions, and the alumni "skills applied" picker that jumped to the top."""
import json
from pathlib import Path
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import CurriculumSurveyResponse, CustomUser
from .helpers import IsolatedDataMixin

STATIC = Path(__file__).resolve().parent.parent / "static" / "myapp"
LOCMEM = "django.core.mail.backends.locmem.EmailBackend"


@override_settings(EMAIL_BACKEND=LOCMEM)
class PasswordResetEmailTests(TestCase):
    def setUp(self):
        cache.clear()

    def ask(self, email, **extra):
        return self.client.post(reverse("forgot_password"), {"email": email, **extra})

    def test_normal_account_gets_the_email(self):
        CustomUser.objects.create_user(email="ana@ue.edu.ph", password="secret123", first_name="A", last_name="B")
        self.ask("ana@ue.edu.ph")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ana@ue.edu.ph"])
        self.assertIn("/reset-password/", mail.outbox[0].body)

    def test_uppercase_typed_email_still_gets_it(self):
        CustomUser.objects.create_user(email="ben@ue.edu.ph", password="secret123", first_name="B", last_name="C")
        self.ask("  BEN@UE.EDU.PH ")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ben@ue.edu.ph"])

    def test_google_registered_student_without_a_password_gets_it(self):
        user = CustomUser.objects.create_user(email="cara@gmail.com", password=None, first_name="C", last_name="D",
                                              role=CustomUser.Role.STUDENT)
        user.set_unusable_password()
        user.save()
        self.ask("cara@gmail.com")
        self.assertEqual(len(mail.outbox), 1)
        link = mail.outbox[0].body.split("http://testserver", 1)[1].split()[0]
        self.assertContains(self.client.get(link), "Choose a new password")

    def test_resend_waits_30_seconds_with_a_countdown_button(self):
        from .. import email_verification
        self.assertEqual(email_verification.RESEND_WAIT_SECONDS, 30)
        CustomUser.objects.create_user(email="dan@ue.edu.ph", password="secret123", first_name="D", last_name="E")
        page = self.ask("dan@ue.edu.ph")
        self.assertContains(page, 'data-countdown="30"')
        self.assertContains(page, 'name="resend" value="1"')
        self.assertContains(page, "resend-countdown.js")
        self.assertContains(self.ask("dan@ue.edu.ph", resend="1"), "Please wait 30 seconds")
        self.assertEqual(len(mail.outbox), 1)
        cache.clear()   # 30 seconds later
        self.assertContains(self.ask("dan@ue.edu.ph", resend="1"), "We sent the link again.")
        self.assertEqual(len(mail.outbox), 2)

    def test_a_failed_send_is_logged_and_can_be_retried_at_once(self):
        CustomUser.objects.create_user(email="eve@ue.edu.ph", password="secret123", first_name="E", last_name="F")
        with mock.patch("myapp.email_verification.send_mail", side_effect=OSError("smtp down")), \
                self.assertLogs("myapp.email_verification", level="ERROR"):
            r = self.ask("eve@ue.edu.ph")
        self.assertContains(r, "has a UEnvision account")   # same answer on screen
        self.ask("eve@ue.edu.ph")                           # no 30 s wait after a failure
        self.assertEqual(len(mail.outbox), 1)

    def test_countdown_script(self):
        js = (STATIC / "resend-countdown.js").read_text(encoding="utf-8")
        self.assertIn("'Resend in ' + left + 's'", js)


class DeveloperAlumniViewTests(IsolatedDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.dev = CustomUser.objects.create_user(email="dev@ue.edu.ph", password="x" * 12, first_name="D",
                                                  last_name="V", role=CustomUser.Role.DEVELOPER)
        CurriculumSurveyResponse.objects.create(respondent_type="professor", user=self.dev, data={"subjects": []})
        self.client.force_login(self.dev)

    def test_switch_has_three_views(self):
        page = self.client.get(reverse("dashboard"))
        for label in ("Faculty view", "Student view", "Alumni view"):
            self.assertContains(page, label)

    def test_alumni_view_shows_the_alumni_skill_gap_page(self):
        self.client.post(reverse("developer_results"), {"view": "alumni", "next": reverse("dashboard")})
        for name in ("dashboard", "recommendations"):
            page = self.client.get(reverse(name))
            self.assertTemplateUsed(page, "student_dashboard.html")
            self.assertContains(page, "<strong>Alumni view.</strong>")
            self.assertEqual(page.context["survey_url"], reverse("alumni_survey"))
            self.assertContains(page, 'value="alumni" class="results-switch-btn is-active" aria-pressed="true"')
        self.client.post(reverse("developer_results"), {"view": "student"})
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, "<strong>Student view.</strong>")
        self.assertEqual(page.context["survey_url"], reverse("student_survey"))
        self.client.post(reverse("developer_results"), {"view": "faculty"})
        self.assertTemplateUsed(self.client.get(reverse("dashboard")), "dashboard.html")

    def test_old_sessions_with_true_still_mean_student(self):
        session = self.client.session
        session["dev_student_view"] = True
        session.save()
        self.assertContains(self.client.get(reverse("dashboard")), "<strong>Student view.</strong>")

    def test_administrators_cannot_use_it(self):
        admin = CustomUser.objects.create_user(email="adm@ue.edu.ph", password="x" * 12, first_name="A",
                                               last_name="D", role=CustomUser.Role.ADMINISTRATOR)
        self.client.force_login(admin)
        self.assertEqual(self.client.post(reverse("developer_results"), {"view": "alumni"}).status_code, 403)


class SkillSuggestionTests(IsolatedDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        from .. import skill_suggestions
        skill_suggestions.clear_cache()

    def test_faculty_reported_skills_come_first_without_duplicates(self):
        from .. import curriculum_data, skill_suggestions
        code = next(c for c, i in curriculum_data.subject_by_code().items() if i["name"] == "Computer Programming 1")
        for i in range(2):
            prof = CustomUser.objects.create_user(email=f"p{i}@ue.edu.ph", password="x" * 12, first_name="P",
                                                  last_name=str(i), role=CustomUser.Role.FACULTY)
            CurriculumSurveyResponse.objects.create(respondent_type="professor", user=prof, data={"subjects": [
                {"code": code, "skills": [{"name": "Rust", "level": "applied"}, {"name": "python", "level": "applied"}]}]})
        skill_suggestions.clear_cache()
        ranked = skill_suggestions.ranked_subject_skill_map()[code]
        self.assertEqual(ranked[:2], ["Rust", "python"])
        self.assertEqual(sum(1 for n in ranked if n.lower() == "python"), 1)   # no "Python" twice
        self.assertIn("Pseudocode", ranked)                                     # curated list still there
        self.assertLessEqual(len(ranked), skill_suggestions.MAX_SUGGESTIONS)

    def test_dummy_answers_do_not_count(self):
        from .. import curriculum_data, skill_suggestions
        code = next(iter(curriculum_data.subject_by_code()))
        CurriculumSurveyResponse.objects.create(respondent_type="professor", is_dummy=True, data={"subjects": [
            {"code": code, "skills": [{"name": "Cobol", "level": "applied"}]}]})
        skill_suggestions.clear_cache()
        self.assertNotIn("Cobol", skill_suggestions.ranked_subject_skill_map()[code])

    def test_electives_and_added_subjects_get_suggestions(self):
        from .. import curriculum_data, skill_suggestions
        electives = [c for c, i in curriculum_data.subject_by_code().items() if "Elective" in i["name"]]
        for code in electives:
            self.assertTrue(skill_suggestions.ranked_subject_skill_map()[code], code)
        self.assertEqual(skill_suggestions.title_matches("Advanced Database Systems")[:2], ["SQL", "MySQL"])
        self.assertIn("Android", skill_suggestions.title_matches("Mobile Application Development"))
        self.assertEqual(skill_suggestions.title_matches("Ethics"), [])

    def test_counts_are_untouched(self):
        """The gap analysis keeps using the plain curated lists."""
        from .. import ontology
        self.assertIn("ranked_subject_skill_map", (Path(__file__).resolve().parent.parent / "views" / "surveys.py").read_text(encoding="utf-8"))
        self.assertNotIn("skill_suggestions", (Path(__file__).resolve().parent.parent / "gap_analysis.py").read_text(encoding="utf-8"))
        self.assertTrue(ontology.subject_skill_map())

    def test_survey_pages_send_the_keyword_table(self):
        from .helpers import login_administrator
        login_administrator(self.client)
        for name in ("student_survey", "alumni_survey", "professor_survey"):
            html = self.client.get(reverse(name)).content.decode()
            boot = json.loads(html.split('<script type="application/json" id="cs-bootstrap">', 1)[1].split("</script>", 1)[0])
            self.assertTrue(boot["keywordSkills"], name)
            self.assertTrue(boot["skills"], name)


class AlumniAppliedPickerJumpTests(TestCase):
    """Adding a skill to "Which technical skills were you able to apply in this job?" made the
    page jump up: the picker's box had no .cs-skill-picker (position: relative), so its
    suggestion list sat far up the page and scrollIntoView() scrolled the window there."""

    def test_the_box_is_a_positioned_picker(self):
        tpl = (Path(__file__).resolve().parent.parent / "templates" / "alumni_survey.html").read_text(encoding="utf-8")
        self.assertIn('<div class="cs-skill-picker" id="alumni-skills-applied-picker"></div>', tpl)
        js = (STATIC / "curriculum-survey.js").read_text(encoding="utf-8")
        self.assertIn("container.classList.add('cs-skill-picker');", js)

    def test_highlighting_a_suggestion_never_scrolls_the_page(self):
        js = (STATIC / "curriculum-survey.js").read_text(encoding="utf-8")
        set_active = js.split("function setActive(i) {", 1)[1].split("\n    }\n", 1)[0]
        self.assertNotIn(".scrollIntoView(", set_active)
        self.assertIn("resultsBox.scrollTop", set_active)

    def test_employment_questions_follow_a_restored_answer(self):
        js = (STATIC / "cs-alumni.js").read_text(encoding="utf-8")
        self.assertIn("function syncBranches()", js)
        self.assertIn("window.addEventListener('pageshow', syncBranches);", js)
