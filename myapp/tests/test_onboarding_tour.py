"""Onboarding tours (onboarding-tour.js): the config every logged-in page carries, saving a
tour as seen, the promotion to administrator, the replay links and the page parts the steps
point at."""
import json
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import CustomUser
from .helpers import IsolatedDataMixin

APP = Path(__file__).resolve().parent.parent
STATIC = APP / "static" / "myapp"
TEMPLATES = APP / "templates"


def make(email, role, **extra):
    return CustomUser.objects.create_user(email=email, password="secret123", first_name="T", last_name="User",
                                          role=role, **extra)


def tour_config(html):
    m = re.search(r'<script id="ue-tour-config" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(m.group(1)) if m else None


class TourConfigTests(TestCase):
    def test_logged_in_pages_carry_the_config_and_script(self):
        fac = make("fac@ue.edu.ph", CustomUser.Role.FACULTY)
        self.client.force_login(fac)
        html = self.client.get(reverse("dashboard")).content.decode()
        cfg = tour_config(html)
        self.assertEqual(cfg["seen"], [])
        self.assertFalse(cfg["admin"])
        self.assertEqual(cfg["saveUrl"], reverse("tour_seen"))
        self.assertIn("onboarding-tour.js", html)
        self.assertIn("onboarding-tour.css", html)
        self.assertIn('data-page="dashboard"', html)
        self.assertNotIn(reverse("accounts"), html)

    def test_logged_out_pages_have_no_tour(self):
        html = self.client.get(reverse("login")).content.decode()
        self.assertIsNone(tour_config(html))
        self.assertNotIn("onboarding-tour.js", html)

    def test_administrators_are_flagged(self):
        admin = make("adm@ue.edu.ph", CustomUser.Role.ADMINISTRATOR)
        self.client.force_login(admin)
        cfg = tour_config(self.client.get(reverse("dashboard")).content.decode())
        self.assertTrue(cfg["admin"])

    def test_old_combined_admin_tour_counts_as_both(self):
        # accounts that saw the old Data Extraction + Accounts tour don't get either part again
        admin = make("old@ue.edu.ph", CustomUser.Role.ADMINISTRATOR, tours_seen=["results", "admin"])
        self.client.force_login(admin)
        cfg = tour_config(self.client.get(reverse("dashboard")).content.decode())
        self.assertEqual(cfg["seen"], ["results", "extraction", "accounts"])


class TourSeenTests(TestCase):
    def setUp(self):
        self.user = make("stu@ue.edu.ph", CustomUser.Role.STUDENT)
        self.client.force_login(self.user)

    def test_marks_a_tour_seen_once(self):
        url = reverse("tour_seen")
        for _ in range(2):
            r = self.client.post(url, {"tour": "results"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
            self.assertEqual(r.status_code, 200)
        self.client.post(url, {"tour": "survey"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.tours_seen, ["results", "survey"])
        cfg = tour_config(self.client.get(reverse("help")).content.decode())
        self.assertEqual(cfg["seen"], ["results", "survey"])

    def test_admin_page_tours_are_saved_separately(self):
        self.client.force_login(make("adm@ue.edu.ph", CustomUser.Role.ADMINISTRATOR))
        self.client.post(reverse("tour_seen"), {"tour": "extraction"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        cfg = tour_config(self.client.get(reverse("help")).content.decode())
        self.assertEqual(cfg["seen"], ["extraction"])
        self.client.post(reverse("tour_seen"), {"tour": "accounts"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        cfg = tour_config(self.client.get(reverse("help")).content.decode())
        self.assertEqual(cfg["seen"], ["extraction", "accounts"])

    def test_unknown_tour_and_get_are_refused(self):
        self.assertEqual(self.client.post(reverse("tour_seen"), {"tour": "nope"}).status_code, 400)
        self.assertEqual(self.client.post(reverse("tour_seen"), {"tour": "admin"}).status_code, 400)
        self.assertEqual(self.client.get(reverse("tour_seen")).status_code, 405)
        self.user.refresh_from_db()
        self.assertEqual(self.user.tours_seen, [])

    def test_needs_login(self):
        self.client.logout()
        r = self.client.post(reverse("tour_seen"), {"tour": "survey"})
        self.assertNotEqual(r.status_code, 200)

    @override_settings(REQUIRE_LEARNER_SURVEY=True)
    def test_allowed_before_the_survey_is_answered(self):
        # the survey tour is skipped or finished on the survey page, before any answer exists
        r = self.client.post(reverse("tour_seen"), {"tour": "survey"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.status_code, 200)

    @override_settings(REQUIRE_PROFESSOR_SURVEY=True)
    def test_allowed_before_the_professor_survey_is_answered(self):
        self.client.force_login(make("newfac@ue.edu.ph", CustomUser.Role.FACULTY))
        r = self.client.post(reverse("tour_seen"), {"tour": "survey"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.status_code, 200)


class PromotionTests(TestCase):
    def setUp(self):
        self.admin = make("boss@ue.edu.ph", CustomUser.Role.ADMINISTRATOR)
        self.fac = make("zed@ue.edu.ph", CustomUser.Role.FACULTY, tours_seen=["survey", "results", "extraction", "accounts"])
        self.client.force_login(self.admin)
        self.fields = {"last_name": "User", "first_name": "T", "email": "zed@ue.edu.ph"}

    def test_promotion_to_administrator_makes_both_admin_tours_unseen(self):
        self.client.post(reverse("account_edit", args=[self.fac.pk]), {**self.fields, "account_type": "administrator"})
        self.fac.refresh_from_db()
        self.assertEqual(self.fac.role, "administrator")
        self.assertEqual(self.fac.tours_seen, ["survey", "results"])

    def test_other_edits_keep_the_tours(self):
        self.client.post(reverse("account_edit", args=[self.fac.pk]), {**self.fields, "first_name": "Zed", "account_type": "faculty"})
        self.fac.refresh_from_db()
        self.assertEqual(self.fac.tours_seen, ["survey", "results", "extraction", "accounts"])

    def test_promotion_also_clears_the_old_combined_tour(self):
        old = make("old@ue.edu.ph", CustomUser.Role.FACULTY, tours_seen=["survey", "admin"])
        self.client.post(reverse("account_edit", args=[old.pk]),
                         {"last_name": "User", "first_name": "T", "email": "old@ue.edu.ph", "account_type": "administrator"})
        old.refresh_from_db()
        self.assertEqual(old.tours_seen, ["survey"])

    def test_an_administrator_staying_one_keeps_it(self):
        other = make("adm2@ue.edu.ph", CustomUser.Role.ADMINISTRATOR, tours_seen=["extraction", "accounts"])
        self.client.post(reverse("account_edit", args=[other.pk]),
                         {"last_name": "User", "first_name": "T", "email": "adm2@ue.edu.ph", "account_type": "administrator"})
        other.refresh_from_db()
        self.assertEqual(other.tours_seen, ["extraction", "accounts"])


class ReplayLinkTests(TestCase):
    def test_learner_gets_survey_and_results_tours(self):
        self.client.force_login(make("alum@ue.edu.ph", CustomUser.Role.ALUMNI))
        html = self.client.get(reverse("help")).content.decode()
        self.assertIn(reverse("alumni_survey") + "?tour=survey", html)
        self.assertIn(reverse("student_dashboard") + "?tour=results", html)
        self.assertNotIn("?tour=extraction", html)
        self.assertNotIn("?tour=accounts", html)

    def test_administrator_also_gets_the_two_admin_tours(self):
        self.client.force_login(make("adm@ue.edu.ph", CustomUser.Role.ADMINISTRATOR))
        html = self.client.get(reverse("help")).content.decode()
        self.assertIn(reverse("professor_survey") + "?tour=survey", html)
        self.assertIn(reverse("dashboard") + "?tour=results", html)
        self.assertIn(reverse("data_extraction") + "?tour=extraction", html)
        self.assertIn(reverse("accounts") + "?tour=accounts", html)
        self.assertNotIn("?tour=admin", html)


class TourTargetTests(IsolatedDataMixin, TestCase):
    """Every page part a step points at is on its page, so a renamed element shows up here
    instead of the step silently being skipped."""

    def test_menu_items_are_named(self):
        html = (TEMPLATES / "app_base.html").read_text(encoding="utf-8")
        for key in ("nav-gap", "nav-skills", "nav-dashboard", "nav-recs", "nav-data", "nav-help", "nav-console", "nav-accounts"):
            self.assertIn(f'data-tour="{key}"', html)

    def test_survey_pages(self):
        from .helpers import login_administrator
        login_administrator(self.client)
        js = (STATIC / "onboarding-tour.js").read_text(encoding="utf-8")
        for url_name, p in (("student_survey", "student"), ("alumni_survey", "alumni"), ("professor_survey", "professor")):
            html = self.client.get(reverse(url_name)).content.decode()
            for needle in (f'id="{p}-survey-form"', 'class="survey-purpose"', f'id="{p}-privacy"',
                           f'id="{p}-subject-blocks"', "cs-submit-row"):
                self.assertIn(needle, html, f"{url_name}: {needle}")
        # the skill box and subject boxes the survey script draws
        cs = (STATIC / "curriculum-survey.js").read_text(encoding="utf-8")
        self.assertIn("cs-tag-input", cs)
        self.assertIn("cs-subject-block", cs)
        self.assertIn("What is a technical skill?", js)
        self.assertIn("Search for a skill and add it", js)
        # the hands-on steps wait on the real subject boxes and skill chips
        self.assertIn("cs-subject-pick:checked", js)
        self.assertIn("cs-chip", cs)
        self.assertIn('id="student-current-subjects"', self.client.get(reverse("student_survey")).content.decode())

    def test_select_all_subjects_from_every_year(self):
        from .helpers import login_administrator
        login_administrator(self.client)
        html = self.client.get(reverse("student_survey")).content.decode()
        self.assertIn('id="student-select-all-years"', html)
        self.assertIn("#student-earlier-subjects .cs-subject-grid", html)
        self.assertNotIn("#student-later-subjects .cs-subject-grid", html)   # higher years stay optional
        html = self.client.get(reverse("alumni_survey")).content.decode()
        self.assertIn('id="alumni-select-all-years"', html)
        self.assertIn('data-select-all="#alumni-subjects .cs-subject-grid"', html)

    def test_admin_tours_stay_on_their_own_page(self):
        js = (STATIC / "onboarding-tour.js").read_text(encoding="utf-8")
        self.assertIn("function extractionSteps()", js)
        self.assertIn("function accountsSteps()", js)
        self.assertNotIn("adminSteps", js)
        self.assertNotIn("window.location.href", js)   # no tour moves to another page

    def test_admin_pages(self):
        admin = make("adm@ue.edu.ph", CustomUser.Role.ADMINISTRATOR)
        self.client.force_login(admin)
        html = self.client.get(reverse("data_extraction")).content.decode()
        for needle in ('id="page-data-extraction"', 'class="data-tabs"', 'id="scrape"', 'id="skills"',
                       'id="ghost"', 'id="run"', 'id="automation"'):
            self.assertIn(needle, html)
        html = self.client.get(reverse("accounts")).content.decode()
        for needle in ('id="page-accounts"', 'id="add-account-btn"', 'class="acct-toolbar"', 'id="accounts-table"', "row-actions"):
            self.assertIn(needle, html)

    def test_dashboard(self):
        fac = make("fac@ue.edu.ph", CustomUser.Role.FACULTY)
        self.client.force_login(fac)
        html = self.client.get(reverse("dashboard")).content.decode()
        for needle in ('id="page-dashboard"', 'class="stat-grid"', 'id="filter-btn"', 'id="skills-panel"', 'class="tabs"'):
            self.assertIn(needle, html)
