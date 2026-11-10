"""Fixes from the site review (Nov 2026): skill counts that match hard_skills.csv, the
Job Market and the ghost-jobs switch, setting a password after a Google sign-up,
messages the page didn't show, adding skills, the "Skills to build" card, curriculum
suggestions and the homepage footer."""
import csv
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib import messages
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from .. import gap_analysis, ghost_jobs, job_market, job_roles
from ..models import CustomUser
from ..pipeline import manager as pipeline
from ..pipeline.skills_schema import write_skill_csvs

COLUMNS = ["job_id", "job_name", "source", "company_name", "function", "date", "hard_skills", "soft_skills",
           "experience_level", "isTechJob"]
ROWS = [
    ["1", "Data Engineer", "kalibrr", "DataCo", "IT and Software", "2025-02-01T00:00:00+00:00", "Python; SQL", "", "Mid", "True"],
    ["2", "Data Engineer", "kalibrr", "DataCo", "IT and Software", "2025-06-01T00:00:00+00:00", "Python; Industry 4.0", "", "Mid", "True"],
    ["3", "Web Developer", "kalibrr", "WebCo", "IT and Software", "2025-03-01T00:00:00+00:00", "SQL; sql; Industry", "", "Junior", "True"],
    ["4", "Accountant", "kalibrr", "Books Inc", "Accounting and Finance", "2025-04-01T00:00:00+00:00", "SQL; Microsoft Excel", "", "Mid", "False"],
]


class DataFilesMixin:
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp()
        with open(Path(self._tmp) / "extracted_skills.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(COLUMNS)
            w.writerows(ROWS)
        self._override = override_settings(DATA_DIR=Path(self._tmp))
        self._override.enable()
        self._clear()

    def tearDown(self):
        self._override.disable()
        shutil.rmtree(self._tmp, ignore_errors=True)
        self._clear()
        super().tearDown()

    def _clear(self):
        job_market._CACHE.update(stamp=None, rows=None, results={})
        job_roles._CACHE.update(key=None, value=None)
        ghost_jobs._CACHE.update(key=None, value=None)
        pipeline._table_cache.clear()

    def hard_skills_csv(self):
        with open(Path(self._tmp) / "hard_skills.csv", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))


class SkillCountTests(DataFilesMixin, TestCase):
    """B2: what the site counts is what counting hard_skills.csv gives."""

    def test_version_numbers_are_not_merged(self):
        key = lambda s: gap_analysis._standardize(s)[0]
        self.assertNotEqual(key("Industry 4.0"), key("Industry"))
        self.assertNotEqual(key("IEEE 802.11"), key("IEEE"))
        # capitalization, spacing and punctuation still don't split a skill
        self.assertEqual(key("SQL"), key(" sql "))
        self.assertEqual(key("CI/CD"), key("CI CD"))

    def test_hard_skills_csv_has_tech_postings_only(self):
        pipeline.ensure_skill_csvs()
        rows = self.hard_skills_csv()
        self.assertNotIn("Accountant", {r["job_name"] for r in rows})
        self.assertNotIn("Microsoft Excel", {r["skill"] for r in rows})

    def test_counts_match_hard_skills_csv(self):
        pipeline.ensure_skill_csvs()
        from collections import Counter
        from_csv = Counter(gap_analysis._standardize(r["skill"])[0] for r in self.hard_skills_csv())
        bars = {gap_analysis._standardize(b["skill"])[0]: b["count"]
                for b in pipeline.skills_dashboard(top=30)["bars"]}
        self.assertEqual(bars, dict(from_csv))
        self.assertEqual(bars[gap_analysis._standardize("SQL")[0]], 2)   # the accountant's SQL isn't counted
        self.assertEqual(bars[gap_analysis._standardize("Industry 4.0")[0]], 1)
        self.assertEqual(bars[gap_analysis._standardize("Industry")[0]], 1)

    def test_old_skill_csvs_are_rebuilt_once(self):
        # hard_skills.csv written by the old code (accountant included), newer than the extracted file
        write_skill_csvs([{"job_name": "Accountant", "hard_skills": "SQL"}], self._tmp)
        pipeline.ensure_skill_csvs()
        self.assertNotIn("Accountant", {r["job_name"] for r in self.hard_skills_csv()})
        self.assertEqual((pipeline.state_dir() / "skill_csvs.version").read_text().strip(),
                         pipeline.SKILL_CSVS_VERSION)

    def test_write_skill_csvs_takes_resume_records_too(self):
        write_skill_csvs([{"job_name": "Dev", "hard_skills": ["Go"], "is_tech_job": True},
                          {"job_name": "Nurse", "hard_skills": ["Triage"], "is_tech_job": False}], self._tmp)
        self.assertEqual([r["skill"] for r in self.hard_skills_csv()], ["Go"])

    def test_job_market_counts_tech_postings(self):
        d = job_market.compute(source="", since=2025)
        top = {s["skill"]: s for s in d["top_skills"]}
        self.assertEqual(top["SQL"]["count"], 2)
        self.assertNotIn("Microsoft Excel", top)
        self.assertEqual(top["SQL"]["pct"], round(2 / 3 * 100, 1))


class JobMarketGhostTests(DataFilesMixin, TestCase):
    """B3: the Dashboard's "Exclude possible ghost jobs" switch applies to the Job Market."""

    def test_switch_leaves_out_ghost_jobs(self):
        ghost_jobs.save_settings({**ghost_jobs.DEFAULT_SETTINGS, "flag_hidden_salary": False,
                                  "flag_unverified": False, "min_description_chars": 0})
        everything = job_market.compute(source="", since=2025)
        self.assertEqual(everything["total"], 4)
        self.assertFalse(everything["ghosts_excluded"])
        token = ghost_jobs.EXCLUDE.set(True)
        try:
            d = job_market.compute(source="", since=2025)
        finally:
            ghost_jobs.EXCLUDE.reset(token)
        # "Data Engineer" at DataCo was posted twice: only the newest copy is kept
        self.assertEqual((d["total"], d["ghosts_hidden"]), (3, 1))
        self.assertTrue(d["ghosts_excluded"])
        self.assertEqual({s["skill"]: s["count"] for s in d["top_skills"]}["Python"], 1)

    def test_page_data_follows_the_session_switch(self):
        ghost_jobs.save_settings({**ghost_jobs.DEFAULT_SETTINGS, "flag_hidden_salary": False,
                                  "flag_unverified": False, "min_description_chars": 0})
        user = CustomUser.objects.create_user(email="fac@ue.edu.ph", password="secret123", first_name="F",
                                              last_name="Ac", role=CustomUser.Role.FACULTY)
        self.client.force_login(user)
        session = self.client.session
        session[ghost_jobs.SESSION_KEY] = True
        session.save()
        d = self.client.get(reverse("job_market_data"), {"source": "all", "since": 2025}).json()
        self.assertEqual((d["total"], d["ghosts_hidden"]), (3, 1))


class SetPasswordTests(TestCase):
    """B4: an account made with Continue with Google can set a password in Settings."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(email="g@ue.edu.ph", password=None, first_name="G",
                                                   last_name="Oogle", role=CustomUser.Role.FACULTY)
        self.user.set_unusable_password()
        self.user.save()
        self.client.force_login(self.user)

    def test_settings_offers_set_a_password(self):
        r = self.client.get(reverse("settings"))
        self.assertContains(r, "Set a password")
        self.assertNotContains(r, 'name="current_password"')

    def test_set_without_current_password(self):
        r = self.client.post(reverse("change_password"), {"new_password": "newsecret123",
                                                          "confirm_password": "newsecret123"}, follow=True)
        self.assertContains(r, "Your password has been set")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("newsecret123"))

    def test_with_a_password_the_current_one_is_still_needed(self):
        self.user.set_password("oldsecret123")
        self.user.save()
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("settings")), 'name="current_password"')
        self.client.post(reverse("change_password"), {"current_password": "wrong", "new_password": "newsecret123",
                                                      "confirm_password": "newsecret123"})
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("oldsecret123"))


class LeftoverMessageTests(TestCase):
    """B5: a message is shown on the page the user lands on, even one with no messages spot."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(email="fac@ue.edu.ph", password="secret123", first_name="F",
                                                   last_name="Ac", role=CustomUser.Role.ADMINISTRATOR)
        self.client.force_login(self.user)

    def _queue(self, text):
        # a message queued by an earlier request, like allauth's "Successfully signed in as ..."
        from django.contrib.messages.storage.session import SessionStorage
        request = RequestFactory().get("/")
        request.session = self.client.session
        storage = SessionStorage(request)
        storage.add(messages.SUCCESS, text)
        storage.update(mock.Mock(cookies={}))
        request.session.save()

    def test_dashboard_shows_it(self):
        self._queue("Successfully signed in as fac@ue.edu.ph.")
        self.assertContains(self.client.get(reverse("dashboard")), "Successfully signed in as fac@ue.edu.ph.")
        # ... and it doesn't turn up again on the next page
        self.assertNotContains(self.client.get(reverse("data")), "Successfully signed in")

    def test_pages_with_their_own_spot_show_it_once(self):
        self._queue("Saved it.")
        self.assertContains(self.client.get(reverse("settings")), "Saved it.", count=1)


class SkillAddTests(TestCase):
    """B6: adding a new skill to the catalog needs a login, and is limited per hour."""

    def setUp(self):
        cache.clear()

    def post(self, name):
        return self.client.post(reverse("skill_add"), data=json.dumps({"name": name}), content_type="application/json")

    def test_needs_login(self):
        with mock.patch("myapp.skills_catalog.add_custom_skill") as add:
            self.assertEqual(self.post("Quantum Basket Weaving").status_code, 403)
        add.assert_not_called()

    def test_limited_per_hour(self):
        user = CustomUser.objects.create_user(email="s@ue.edu.ph", password="secret123", first_name="S",
                                              last_name="T", role=CustomUser.Role.STUDENT)
        self.client.force_login(user)
        from .. import student_views
        with mock.patch("myapp.skills_catalog.add_custom_skill", side_effect=lambda n: (n, True, None)), \
                mock.patch.object(student_views, "MAX_NEW_SKILLS_PER_HOUR", 2):
            self.assertEqual(self.post("One").status_code, 200)
            self.assertEqual(self.post("Two").status_code, 200)
            self.assertEqual(self.post("Three").status_code, 429)


class SkillsToBuildCardTests(TestCase):
    """B7: the "Skills to build" card counts every missing top skill, not just the 6 listed."""

    def test_total_before_the_cut(self):
        from .. import rec_context
        user = CustomUser.objects.create_user(email="s@ue.edu.ph", password="secret123", first_name="S",
                                              last_name="T", role=CustomUser.Role.STUDENT,
                                              learner_info={"course": "BSIT", "year_level": "1"})
        skills = [{"key": f"skill {i}", "skill": f"Skill {i}", "count": 1, "pct": 10.0 - i} for i in range(9)]
        fake = {"exists": True, "roles": [], "overall": {"postings": 10, "skills": skills}, "role": None,
                "program": "", "source_label": "Kalibrr"}
        with mock.patch("myapp.job_roles.skill_stats", return_value=fake):
            plan = rec_context.student_plan(user, top=9, max_to_build=6)
        self.assertEqual((len(plan["to_build"]), plan["to_build_total"]), (6, 9 - len(plan["coming_up"])))


class CurriculumSuggestionTests(TestCase):
    """B8: subjects hidden from the subject list (e.g. Capstone) aren't suggested either."""

    def test_capstone_left_out(self):
        from ..views.dashboard import _curriculum_suggestions
        admin = CustomUser.objects.create_user(email="a@ue.edu.ph", password="secret123", first_name="A",
                                               last_name="D", role=CustomUser.Role.ADMINISTRATOR)
        gap = {"exists": True, "by_subject": [
            {"code": "CPP 4980", "could_add": [{"skill": "Jira"}]},
            {"code": "CIT 4102", "could_add": [{"skill": "PowerShell"}]},
        ]}
        self.assertEqual([r["code"] for r in _curriculum_suggestions(admin, gap)], ["CIT 4102"])


class HomeFooterTests(DataFilesMixin, TestCase):
    """B9: the homepage footer names the job boards the data really comes from."""

    def test_footer_lists_sources(self):
        r = self.client.get(reverse("home"))
        self.assertContains(r, "public job boards (Kalibrr)")


# ---------------------------------------------------------------------------
# Nov 10, 2026: two more places where the numbers could be wrong
# ---------------------------------------------------------------------------
OLD_COLUMNS = ["job_id", "job_name", "source", "company_name", "function", "date", "hard_skills", "soft_skills",
               "experience_level"]          # extracted before isTechJob existed: no such column
OLD_ROWS = [
    ["1", "Data Engineer", "kalibrr", "DataCo", "IT and Software", "2025-02-01T00:00:00+00:00", "Python; SQL", "", "Mid"],
    ["2", "Web Developer", "kalibrr", "WebCo", "IT and Software", "2025-03-01T00:00:00+00:00", "SQL", "", "Junior"],
    # no isTechJob answer and not an IT title: the pages leave these out, so the files must too
    ["3", "Accountant", "kalibrr", "Books Inc", "Accounting and Finance", "2025-04-01T00:00:00+00:00", "SQL; Microsoft Excel", "", "Mid"],
    ["4", "Marketing Lead", "kalibrr", "AdCo", "IT and Software", "2025-04-01T00:00:00+00:00", "Python; SEO", "", "Mid"],
]


class UnansweredTechFlagTests(DataFilesMixin, TestCase):
    """Postings whose isTechJob was never answered: hard_skills.csv and the pages use one
    rule (job_roles.record_is_counted), so counting the file gives what the Dashboard shows."""

    def setUp(self):
        super().setUp()
        with open(Path(self._tmp) / "extracted_skills.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(OLD_COLUMNS)
            w.writerows(OLD_ROWS)
        self._clear()

    def test_file_has_the_postings_the_pages_count(self):
        pipeline.ensure_skill_csvs()
        self.assertEqual({r["job_name"] for r in self.hard_skills_csv()}, {"Data Engineer", "Web Developer"})
        self.assertEqual(len(job_roles.it_postings()), 2)

    def test_counts_match_hard_skills_csv(self):
        pipeline.ensure_skill_csvs()
        from collections import Counter
        from_csv = Counter(r["skill"] for r in self.hard_skills_csv())
        bars = {b["skill"]: b["count"] for b in pipeline.skills_dashboard(top=30)["bars"]}
        self.assertEqual(bars, dict(from_csv))
        self.assertEqual(bars, {"SQL": 2, "Python": 1})

    def test_one_rule_for_rows_and_postings(self):
        records = [dict(zip(OLD_COLUMNS, r)) for r in OLD_ROWS] + [dict(zip(COLUMNS, r)) for r in ROWS]
        self.assertEqual([job_roles.record_is_counted(r) for r in records],
                         [True, True, False, False, True, True, True, False])
        self.assertTrue(job_roles.record_is_counted({"job_name": "Nurse", "is_tech_job": True}))
        self.assertFalse(job_roles.record_is_counted({"job_name": "Software Developer", "is_tech_job": False}))


class StaffTryOutSurveyTests(TestCase):
    """A professor or administrator trying the Student / Alumni Survey out is not a student:
    the answers go to the dummy data set and never count in the real results."""

    def test_is_dummy_for_staff_but_not_for_learners(self):
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory

        from ..models import CustomUser
        from ..views.surveys import _is_dummy

        def as_user(role, email, **extra):
            request = RequestFactory().post("/")
            request.user = CustomUser.objects.create_user(email=email, password="secret123", first_name="A",
                                                          last_name="B", role=role, **extra)
            return bool(_is_dummy(request))

        self.assertTrue(as_user(CustomUser.Role.FACULTY, "prof@ue.edu.ph"))
        self.assertTrue(as_user(CustomUser.Role.ADMINISTRATOR, "admin@ue.edu.ph"))
        self.assertTrue(as_user(CustomUser.Role.DEVELOPER, "dev@ue.edu.ph"))
        self.assertFalse(as_user(CustomUser.Role.STUDENT, "stud@ue.edu.ph"))
        self.assertFalse(as_user(CustomUser.Role.ALUMNI, "alum@ue.edu.ph"))
        self.assertTrue(as_user(CustomUser.Role.STUDENT, "test@ue.edu.ph", is_dummy=True))
        request = RequestFactory().post("/")
        request.user = AnonymousUser()
        self.assertFalse(_is_dummy(request))
