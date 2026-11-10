"""Job Market page: the numbers behind its charts, and who can open it."""
import csv
import shutil
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from .. import job_market
from ..models import CustomUser

COLUMNS = ["job_id", "job_name", "source", "company_name", "function", "work_mode", "city",
           "base_salary", "maximum_salary", "salary_currency", "salary_interval", "date",
           "open_to_fresh_grads", "hard_skills", "experience_level", "isTechJob"]

ROWS = [
    # 2024: two tech postings with HTML, one non-tech
    ["1", "Web Developer", "kalibrr", "Acme", "IT and Software", "On-site", "Makati", "20000", "30000", "PHP", "month",
     "2024-02-01T00:00:00+00:00", "True", "HTML; CSS; JavaScript", "Entry", "True"],
    ["2", "Front End Developer", "kalibrr", "Acme", "IT and Software", "Hybrid", "Taguig", "", "", "", "",
     "2024-05-10T00:00:00+00:00", "False", "HTML; React", "Junior", "True"],
    ["3", "Accountant", "kalibrr", "Books Inc", "Accounting and Finance", "On-site", "Makati", "30000", "", "PHP", "month",
     "2024-06-10T00:00:00+00:00", "False", "Microsoft Excel", "Mid", "False"],
    # 2026: two tech postings with Python, no HTML
    ["4", "Data Engineer", "kalibrr", "DataCo", "IT and Software", "Hybrid", "Taguig", "80000", "100000", "PHP", "month",
     "2026-01-15T00:00:00+00:00", "False", "Python; SQL", "Senior", "True"],
    ["5", "Data Analyst", "kalibrr", "DataCo", "IT and Software", "Work from home", "Pasig", "", "", "", "",
     "2026-08-01T00:00:00+00:00", "True", "Python; Excel", "Entry", "True"],
    # another source and an older posting, left out by the default filters
    ["6", "Developer", "foundit", "Elsewhere", "IT and Software", "On-site", "Cebu", "", "", "", "",
     "2026-03-01T00:00:00+00:00", "False", "Go", "Mid", "True"],
    ["7", "Developer", "kalibrr", "OldCo", "IT and Software", "On-site", "Makati", "", "", "", "",
     "2019-03-01T00:00:00+00:00", "False", "Perl", "Mid", "True"],
    # an imported public dataset (Ukrainian postings): only counted when its box is ticked
    ["djinni-1", "Developer", "djinni", "KyivSoft", "IT and Software", "Remote", "Kyiv", "", "", "", "",
     "2025-03-01T00:00:00+00:00", "", "Rust", "Mid", "True"],
]
KALIBRR = ["kalibrr"]


class JobMarketTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        with open(Path(self._tmp) / "extracted_skills.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(COLUMNS)
            w.writerows(ROWS)
        self._override = override_settings(DATA_DIR=Path(self._tmp))
        self._override.enable()
        job_market._CACHE.update(stamp=None, rows=None, results={})
        self.faculty = CustomUser.objects.create_user(email="fac@ue.edu.ph", password="secret123",
                                                      first_name="F", last_name="Aculty")

    def tearDown(self):
        self._override.disable()
        shutil.rmtree(self._tmp, ignore_errors=True)
        job_market._CACHE.update(stamp=None, rows=None, results={})

    def test_kalibrr_from_2024(self):
        d = job_market.compute(KALIBRR)
        self.assertEqual(d["total"], 5)
        self.assertEqual(d["tech_total"], 4)
        self.assertEqual(d["years"], [2024, 2026])
        self.assertEqual((d["first_month"], d["last_month"]), ("2024-02", "2026-08"))

    def test_skills_are_counted_as_written_once_per_posting(self):
        d = job_market.compute(KALIBRR)
        top = {s["skill"]: s for s in d["top_skills"]}
        self.assertEqual(top["HTML"]["count"], 2)
        self.assertEqual(top["HTML"]["by_year"], [2, 0])
        self.assertEqual(top["Python"]["count"], 2)
        # "Excel" stays as written in the data set ...
        self.assertIn("Excel", top)
        # ... and the accountant's "Microsoft Excel" isn't counted: skills come from tech
        # postings only, like the Dashboard and hard_skills.csv
        self.assertNotIn("Microsoft Excel", top)
        self.assertEqual(top["HTML"]["pct"], 50.0)   # 2 of the 4 tech postings
        self.assertNotIn("Go", top)
        self.assertNotIn("Perl", top)

    def test_quarters_split_tech_and_non_tech_and_fill_gaps(self):
        d = job_market.compute(KALIBRR)
        q = {r["label"]: r for r in d["quarters"]}
        self.assertEqual((q["Q2 2024"]["tech"], q["Q2 2024"]["nontech"]), (1, 1))
        self.assertEqual((q["Q2 2025"]["tech"], q["Q2 2025"]["nontech"]), (0, 0))
        self.assertTrue(d["quarters"][-1]["partial"])
        self.assertEqual(d["quarters"][-1]["label"], "Q3 2026")

    def test_rising_and_falling_use_tech_postings(self):
        d = job_market.compute(KALIBRR)
        shift = d["shift"]
        self.assertEqual((shift["from_year"], shift["to_year"]), (2024, 2026))
        rising = {m["skill"]: m for m in shift["rising"]}
        falling = {m["skill"]: m for m in shift["falling"]}
        self.assertEqual(rising["Python"]["to"], 100.0)
        self.assertEqual(falling["HTML"]["from"], 100.0)
        self.assertNotIn("Microsoft Excel", rising)  # only in a non-tech posting

    def test_pay_uses_php_monthly_midpoints(self):
        d = job_market.compute(KALIBRR)
        pay = {p["level"]: p for p in d["pay"]}
        self.assertEqual(pay["Entry"]["median"], 25000)
        self.assertEqual(pay["Senior"]["median"], 90000)
        self.assertEqual(pay["Mid"]["median"], 30000)
        self.assertEqual(d["priced"], 3)

    def test_all_sources_and_since_filter(self):
        d = job_market.compute(["kalibrr", "foundit"], 2015)
        self.assertEqual(d["total"], 7)
        self.assertEqual(job_market.compute("foundit", 2024)["total"], 1)

    def test_defaults_to_the_job_boards_without_djinni(self):
        d = job_market.compute()
        self.assertEqual(d["total"], 6)                   # 5 Kalibrr + 1 Foundit, no Djinni
        self.assertEqual(d["sources"], ["kalibrr", "foundit"])
        self.assertEqual(d["source_label"], "Kalibrr and Foundit")
        self.assertNotIn("Rust", {s["skill"] for s in d["top_skills"]})

    def test_djinni_can_be_ticked_in(self):
        d = job_market.compute(["kalibrr", "foundit", "djinni"])
        self.assertEqual(d["total"], 7)
        self.assertIn("Rust", {s["skill"] for s in d["top_skills"]})
        self.assertEqual(job_market.compute(["djinni"])["total"], 1)

    def test_sources_available_lists_datasets_last_and_unticked(self):
        self.assertEqual(job_market.sources_available(), [
            {"key": "kalibrr", "label": "Kalibrr", "dataset": False, "default": True},
            {"key": "foundit", "label": "Foundit", "dataset": False, "default": True},
            {"key": "djinni", "label": "Djinni", "dataset": True, "default": False},
        ])

    def test_picks_up_new_postings_without_restart(self):
        self.assertEqual(job_market.compute(KALIBRR)["total"], 5)
        import os, time
        path = Path(self._tmp) / "extracted_skills.csv"
        with open(path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["8", "QA Engineer", "kalibrr", "TestCo", "IT and Software", "Hybrid", "Makati",
                                    "", "", "", "", "2026-09-01T00:00:00+00:00", "False", "Selenium", "Mid", "True"])
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        self.assertEqual(job_market.compute(KALIBRR)["total"], 6)

    def test_page_and_data_for_faculty(self):
        self.client.force_login(self.faculty)
        r = self.client.get(reverse("job_market"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Job Market")
        self.assertContains(r, 'type="checkbox" name="source" value="kalibrr" checked')
        self.assertContains(r, 'type="checkbox" name="source" value="foundit" checked')
        self.assertContains(r, 'type="checkbox" name="source" value="djinni">')
        self.assertContains(r, "imported dataset")
        r = self.client.get(reverse("job_market_data"), {"source": "all", "since": "2024"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["total"], 6)
        self.assertEqual(self.client.get(reverse("job_market_data"), {"since": "2024"}).json()["total"], 6)
        r = self.client.get(reverse("job_market_data") + "?source=kalibrr&source=djinni&since=2024")
        self.assertEqual(r.json()["total"], 6)            # 5 Kalibrr + 1 Djinni
        self.assertEqual(r.json()["sources"], ["kalibrr", "djinni"])
        self.assertEqual(self.client.get(reverse("job_market_data"), {"source": "indeed"}).status_code, 400)
        self.assertEqual(self.client.get(reverse("job_market_data"), {"since": "abc"}).status_code, 400)

    def test_students_are_kept_out(self):
        student = CustomUser.objects.create_user(email="stud@ue.edu.ph", password="secret123", first_name="S",
                                                 last_name="Tudent", role=CustomUser.Role.STUDENT)
        self.client.force_login(student)
        self.assertEqual(self.client.get(reverse("job_market")).status_code, 302)
        self.assertEqual(self.client.get(reverse("job_market_data")).status_code, 302)

    def test_login_required(self):
        self.assertEqual(self.client.get(reverse("job_market_data")).status_code, 302)

    def test_no_data_yet(self):
        (Path(self._tmp) / "extracted_skills.csv").unlink()
        job_market._CACHE.update(stamp=None, rows=None, results={})
        self.assertEqual(job_market.compute(KALIBRR), {"exists": False})
