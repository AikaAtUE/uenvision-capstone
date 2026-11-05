"""Third batch of system edits: emails are case-insensitive, only faculty need approval,
sortable Accounts table with a Status column, developers can edit the Feedback forms,
"Data last updated" under the charts, longer skill suggestion lists with "Select all shown",
and the homepage introduction."""
import json
from pathlib import Path

from django.contrib.auth import authenticate
from django.test import TestCase
from django.urls import reverse

from ..models import CustomUser, FeedbackForm
from .helpers import IsolatedDataMixin

STATIC = Path(__file__).resolve().parent.parent / "static" / "myapp"
TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def make(email, role=CustomUser.Role.FACULTY, **extra):
    return CustomUser.objects.create_user(email=email, password="secret12345", first_name="F",
                                          last_name="L", role=role, **extra)


class EmailCaseTests(TestCase):
    def test_email_is_saved_in_lowercase(self):
        self.assertEqual(make("Ana.Cruz@UE.edu.PH").email, "ana.cruz@ue.edu.ph")

    def test_any_capitalization_logs_in(self):
        make("ben@ue.edu.ph")
        self.assertIsNotNone(authenticate(email="BEN@UE.EDU.PH", password="secret12345"))
        self.assertIsNotNone(authenticate(email="Ben@ue.edu.ph", password="secret12345"))


class ApprovalTests(TestCase):
    def test_students_and_alumni_never_wait_for_approval(self):
        for i, role in enumerate((CustomUser.Role.STUDENT, CustomUser.Role.ALUMNI, CustomUser.Role.ADMINISTRATOR)):
            self.assertTrue(make(f"u{i}@ue.edu.ph", role=role, is_approved=False).is_approved)

    def test_faculty_still_need_it(self):
        self.assertFalse(make("fac@ue.edu.ph", is_approved=False).is_approved)


class AccountsTableTests(TestCase):
    def setUp(self):
        self.admin = make("admin@ue.edu.ph", role=CustomUser.Role.ADMINISTRATOR)
        self.client.force_login(self.admin)
        self.fac = make("waiting@ue.edu.ph", is_approved=False)
        make("stud@ue.edu.ph", role=CustomUser.Role.STUDENT)

    def test_status_column_and_pending_filter(self):
        page = self.client.get(reverse("accounts"))
        self.assertContains(page, "Status")
        self.assertContains(page, "Not approved yet")
        statuses = page.content.decode().split('<td class="acct-status">')[1:]
        self.assertEqual(len(statuses), 3)
        self.assertFalse(any("Deactivated" in cell.split("</td>")[0] for cell in statuses))
        pending = self.client.get(reverse("accounts"), {"state": "pending"})
        self.assertContains(pending, "waiting@ue.edu.ph")
        self.assertNotContains(pending, "stud@ue.edu.ph")

    def test_every_column_sorts_both_ways(self):
        page = self.client.get(reverse("accounts"))
        labels = [c[0] for c in page.context["columns"]]
        for label in ("Name", "Email", "Role", "Status"):
            self.assertIn(label, labels)
        for sort in ("id", "-id", "email", "-email", "role", "-role", "status", "-status"):
            self.assertEqual(self.client.get(reverse("accounts"), {"sort": sort}).status_code, 200, sort)


class FeedbackFormEditTests(TestCase):
    def setUp(self):
        from .. import feedback_forms
        self.forms = feedback_forms
        self.dev = make("dev@ue.edu.ph", role=CustomUser.Role.DEVELOPER)

    def post(self, key, body):
        return self.client.post(reverse("feedback_form_save", args=[key]), json.dumps(body),
                                content_type="application/json")

    def test_developer_edits_and_resets_a_form(self):
        self.client.force_login(self.dev)
        content = dict(self.forms.DEFAULTS["functional"])
        content["purpose"] = "New purpose for everyone"
        content["rows"] = [{"feature": "Login", "scenario": "Log in with Google"}]
        self.assertEqual(self.post("functional", {"content": content}).status_code, 200)
        self.assertEqual(FeedbackForm.objects.get(key="functional").content["purpose"], "New purpose for everyone")
        fac = make("f@ue.edu.ph")
        self.client.force_login(fac)
        page = self.client.get(reverse("feedback"))
        self.assertContains(page, "New purpose for everyone")
        self.assertFalse(page.context["can_edit_forms"])
        self.client.force_login(self.dev)
        self.post("functional", {"reset": True})
        self.assertFalse(FeedbackForm.objects.filter(key="functional").exists())

    def test_others_cannot_edit_and_counts_stay_fixed(self):
        self.client.force_login(make("adm@ue.edu.ph", role=CustomUser.Role.ADMINISTRATOR))
        self.assertEqual(self.post("sus", {"reset": True}).status_code, 403)
        self.client.force_login(self.dev)
        content = dict(self.forms.DEFAULTS["sus"])
        content["questions"] = content["questions"][:-1]
        self.assertEqual(self.post("sus", {"content": content}).status_code, 400)


class DataUpdatedTests(IsolatedDataMixin, TestCase):
    def test_line_follows_the_extracted_data_file(self):
        from ..pipeline import manager
        if manager.skills_data_updated() is None:
            self.skipTest("no extracted skills data in this checkout")
        self.assertContains(self.client.get(reverse("home")), "Data last updated:")


class HomepageIntroTests(IsolatedDataMixin, TestCase):
    def test_intro_comes_first_and_scrolls_to_top_skills(self):
        page = self.client.get(reverse("home")).content.decode()
        self.assertIn('class="land"', page)
        self.assertIn('id="top-skills"', page)
        self.assertLess(page.index('class="land"'), page.index('id="top-skills"'))
        self.assertIn('href="#top-skills"', page)


class LongerSuggestionTests(IsolatedDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        from .. import skill_suggestions
        skill_suggestions.clear_cache()

    def test_lists_are_longer_than_one_screen_and_have_no_repeats(self):
        from ..subject_skills import SUBJECT_SKILLS
        for subject, names in SUBJECT_SKILLS.items():
            lowered = [n.lower() for n in names]
            self.assertEqual(len(lowered), len(set(lowered)), subject)
        self.assertGreater(sum(len(v) > 16 for v in SUBJECT_SKILLS.values()), 30)
        for soft in ("Teamwork", "Communication", "Critical Thinking", "Time Management"):
            self.assertFalse(any(soft in v for v in SUBJECT_SKILLS.values()), soft)

    def test_the_page_gets_the_whole_list(self):
        from .. import skill_suggestions
        ranked = skill_suggestions.ranked_subject_skill_map()
        self.assertTrue(any(len(v) > 16 for v in ranked.values()))

    def test_select_all_takes_only_the_shown_suggestions_without_a_level(self):
        js = (STATIC / "curriculum-survey.js").read_text(encoding="utf-8")
        self.assertIn("var MAX_SHOWN_SUGGESTIONS = 16;", js)
        self.assertIn("data-suggest-all", js)
        self.assertIn("names.forEach(function (n) { addChip(n, '', true); });", js)
        # the visible list skips skills already picked, so it refills from the rest
        self.assertIn(".slice(0, low ? MAX_LOCAL_MATCHES : MAX_SHOWN_SUGGESTIONS)", js)


class WelcomeCardTests(TestCase):
    def test_hidden_on_about_and_how_to_use(self):
        js = (STATIC / "welcome-tips.js").read_text(encoding="utf-8")
        self.assertIn("help", js)
        self.assertIn("about", js)
        self.assertIn('data-page="{{ active_page }}"', (TEMPLATES / "app_base.html").read_text(encoding="utf-8"))
