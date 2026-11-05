"""Possible ghost job detection (ghost_jobs.py): postings are only marked, every result
counts them by default, and the Dashboard's "Exclude possible ghost jobs" switch leaves
them out (keeping the newest copy of a job posted twice)."""
import csv
import json

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from ..models import CustomUser
from .helpers import IsolatedDataMixin

LONG = "x" * 800
# job_id, job_name, company, salary_shown, verified, date, hard skills, description
ROWS = [
    ("1", "Android Developer", "Acme Inc.", "True", "True", "2026-08-01", "Kotlin; Java", LONG),
    ("2", "Android Developer", "ACME", "True", "True", "2026-09-15", "Kotlin; Java", LONG),       # same job, newer
    ("3", "Data Engineer", "Beta Corp", "False", "False", "2026-09-01", "SQL; Python", "Short."),  # 3 weak signs
    ("4", "QA Analyst", "Gamma", "False", "True", "2026-09-01", "Selenium", LONG),                 # 1 weak sign only
    ("5", "Data Engineer", "Delta", "True", "True", "2026-09-01", "SQL; Spark", LONG),            # clean
    ("6", "Data Architect {Lakehouse}", "Epsilon", "True", "True", "2026-09-01", "AWS", LONG),
    ("7", "Data Architect [Landscape]", "Epsilon", "True", "True", "2026-09-02", "Azure", LONG),  # different title
]


class GhostJobTests(IsolatedDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        from .. import ghost_jobs
        ghost_jobs._CACHE.update(key=None, value=None)
        d = settings.DATA_DIR
        with open(d / "extracted_skills.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["job_id", "job_name", "source", "company_name", "company_verified", "salary_shown",
                        "date", "hard_skills", "soft_skills", "experience_level", "isTechJob"])
            for jid, name, company, sal, ver, date, hard, _ in ROWS:
                w.writerow([jid, name, "kalibrr", company, ver, sal, date, hard, "Teamwork", "Entry", "True"])
        with open(d / "compiled_kalibrr.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["job_id", "job_title", "description"])
            for jid, name, *_, desc in ROWS:
                w.writerow([jid, name, desc])
        self.dataset_skill_count = sum(len(r[6].split("; ")) for r in ROWS)

    def tearDown(self):
        from .. import ghost_jobs
        ghost_jobs._CACHE.update(key=None, value=None)
        super().tearDown()

    def login_admin(self):
        user = CustomUser.objects.create_user(email="adm@ue.edu.ph", password="secret123", first_name="A",
                                              last_name="B", role=CustomUser.Role.ADMINISTRATOR)
        self.client.force_login(user)
        return user

    def marked(self):
        from .. import ghost_jobs
        return sorted(jid for (_, jid), info in ghost_jobs.detect().items() if info["flagged"])

    # ---- detection -------------------------------------------------------
    def test_default_signs(self):
        from .. import ghost_jobs
        found = ghost_jobs.detect()
        self.assertEqual(self.marked(), ["1", "2", "3"])
        self.assertIn("Same job also posted as kalibrr #2", found[("kalibrr", "1")]["reasons"])
        self.assertEqual(found[("kalibrr", "3")]["reasons"],
                         ["Salary hidden", "Short description (6 characters)", "Company not verified"])
        self.assertFalse(found[("kalibrr", "4")]["flagged"])      # one weak sign isn't enough
        self.assertFalse(found[("kalibrr", "6")]["flagged"])      # different text in the brackets
        # Excluding keeps the newest copy of the duplicate only.
        self.assertFalse(found[("kalibrr", "1")]["keep_when_excluding"])
        self.assertTrue(found[("kalibrr", "2")]["keep_when_excluding"])
        self.assertFalse(found[("kalibrr", "3")]["keep_when_excluding"])

    def test_settings_change_what_is_marked(self):
        from .. import ghost_jobs
        ghost_jobs.save_settings({**ghost_jobs.DEFAULT_SETTINGS, "weak_signs_needed": 1, "flag_duplicates": False})
        self.assertEqual(self.marked(), ["3", "4"])
        ghost_jobs.save_settings({**ghost_jobs.DEFAULT_SETTINGS, "flag_hidden_salary": False,
                                  "flag_unverified": False, "min_description_chars": 0})
        self.assertEqual(self.marked(), ["1", "2"])

    # ---- the data sets stay as they are -----------------------------------
    def test_default_results_count_every_posting(self):
        from .. import job_roles
        self.assertEqual(len(job_roles.it_postings()), len(ROWS))
        self.assertEqual(len(job_roles.it_postings(exclude_ghosts=True)), len(ROWS) - 2)
        self.login_admin()
        data = self.client.get(reverse("dashboard_skills"), {"top": 30}).json()
        self.assertEqual(data["stats"]["postings"], len(ROWS))
        self.assertEqual(sum(b["count"] for b in data["bars"]), self.dataset_skill_count)
        self.assertEqual(data["ghost"], {"marked": 3, "hidden": 0, "excluded": False})

    def test_exclude_switch_is_remembered_and_applies_elsewhere(self):
        self.login_admin()
        url = reverse("dashboard_skills")
        data = self.client.get(url, {"top": 30, "ghost": "exclude"}).json()
        self.assertEqual(data["stats"]["postings"], len(ROWS) - 2)
        self.assertEqual(data["ghost"], {"marked": 3, "hidden": 2, "excluded": True})
        kotlin = next(b for b in data["bars"] if b["skill"] == "Kotlin")
        self.assertEqual(kotlin["count"], 1)                       # the job posted twice counts once
        # Remembered: a later request without the parameter still excludes.
        self.assertEqual(self.client.get(url, {"top": 30}).json()["stats"]["postings"], len(ROWS) - 2)
        self.assertContains(self.client.get(reverse("dashboard")), 'id="ctl-ghost" checked')
        self.assertContains(self.client.get(reverse("recommendations")), "2 possible ghost jobs excluded")
        # Turned off again: back to every posting.
        self.assertEqual(self.client.get(url, {"top": 30, "ghost": "include"}).json()["stats"]["postings"], len(ROWS))
        self.assertNotContains(self.client.get(reverse("recommendations")), "possible ghost job")

    def test_other_visitors_are_not_affected(self):
        self.login_admin()
        self.client.get(reverse("dashboard_skills"), {"ghost": "exclude"})
        self.client.logout()
        self.assertContains(self.client.get(reverse("home")), f"According to {len(ROWS)} IT/CS job postings")

    # ---- Data -> Ghost Jobs ------------------------------------------------
    def test_ghost_jobs_page_and_settings(self):
        self.login_admin()
        page = self.client.get(reverse("data_ghost_jobs"))
        self.assertContains(page, "3</strong> of 7 postings marked")
        self.assertContains(page, "Kept (newest copy)")
        resp = self.client.post(reverse("data_ghost_jobs"), {"flag_hidden_salary": "on", "flag_unverified": "on",
                                                              "min_description_chars": "500", "weak_signs_needed": "1"})
        self.assertRedirects(resp, reverse("data_ghost_jobs"))
        saved = json.loads((settings.DATA_DIR / ".state" / "ghost_settings.json").read_text())
        self.assertFalse(saved["flag_duplicates"])
        self.assertEqual(saved["weak_signs_needed"], 1)
        self.assertEqual(self.marked(), ["3", "4"])
        bad = self.client.post(reverse("data_ghost_jobs"), {"min_description_chars": "-5", "weak_signs_needed": "2"})
        self.assertContains(bad, "between 0 and")

    def test_faculty_can_view_but_not_change_settings(self):
        faculty = CustomUser.objects.create_user(email="fac@ue.edu.ph", password="secret123", first_name="F",
                                                 last_name="G", role=CustomUser.Role.FACULTY)
        self.client.force_login(faculty)
        page = self.client.get(reverse("data_ghost_jobs"))
        self.assertContains(page, "Only Administrators can change")
        self.assertNotContains(page, 'id="ghost-form"')
        self.assertEqual(self.client.post(reverse("data_ghost_jobs"), {"weak_signs_needed": "1"}).status_code, 403)
