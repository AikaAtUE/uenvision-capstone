"""Foundit (foundit.com.ph), the third job source: the scraper, the compile step, the extraction
layout, Import Data and the Data Extraction steps."""
import csv
import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from ..pipeline import compile_jobs_to_csv as compiler, foundit_scraper, manager as pipeline, sources
from ..pipeline.skills_schema import SOURCE_CONFIG, normalize_record
from .helpers import IsolatedDataMixin


def detail(job_id=69675292, **over):
    """A jobDetail API response, trimmed to the fields the pipeline reads."""
    job = {
        "id": str(job_id), "jobId": job_id, "title": "IT Manager",
        "company": {"companyId": 900375, "name": "Dempsey Resource Management",
                    "logo": "https://media.example/logo.gif"},
        "companyId": 900375, "companyName": "dempsey resource management",
        "companyLogoUrl": "https://media.example/logo.gif",
        "locations": [{"city": "Pasig", "country": "Philippines"}],
        "minimumExperience": {"years": 5}, "maximumExperience": {"years": 7},
        "minimumSalary": {"currency": "PHP", "absoluteValue": 0, "absoluteMonthlyValue": 0},
        "maximumSalary": {"currency": "PHP", "absoluteValue": 0, "absoluteMonthlyValue": 0},
        "postedAt": 1793471080000, "createdAt": 1793471080000, "updatedAt": 1793471080000,
        "closedAt": 1797273000000,
        "industries": ["Other"], "functions": ["Information Technology"],
        "description": "WORK LOCATION<br/><br/>PASIG CITY<br/><ul><li>ERP systems</li></ul>",
        "jobTypes": ["Permanent Job"], "employmentTypes": ["Full time"],
        "skills": [{"text": "Computer Science"}, {"text": "ERP systems"}],
        "itSkills": [{"text": "Information Systems"}],
        "designations": ["IT Manager"], "currencyCode": "PHP", "hideSalary": 0,
        "jobSalaryConfidential": False, "isJobActive": True, "jobSource": "SCRAPPING",
        "applyUrl": "https://apply.example/1",
        "jdUrl": f"/job/it-manager-dempsey-resource-management-philippines-{job_id}",
    }
    job.update(over)
    return job


def search_item(job_id, title="IT Manager"):
    return {"id": str(job_id), "jobId": job_id, "title": title, "company": {"name": "Co"},
            "jdUrl": f"/job/{title.lower().replace(' ', '-')}-co-philippines-{job_id}"}


class TmpDirMixin:
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)


class FounditScraperTests(TmpDirMixin, TestCase):
    def test_search_url_matches_the_site(self):
        url = foundit_scraper.search_url("computer science", 20, 20, ["Philippines", "Japan"])
        self.assertEqual(url, "https://www.foundit.com.ph/home/api/searchResultsPage?start=20&limit=20"
                              "&query=computer+science&queryDerived=true&countries=Philippines"
                              "&countries=Japan&variantName=DEFAULT")

    def test_slug_and_file_name_come_from_the_job_url(self):
        job = detail()
        self.assertEqual(foundit_scraper.job_slug(job), "it-manager-dempsey-resource-management-philippines")
        self.assertEqual(foundit_scraper.job_output_path(self.tmp, 69675292, foundit_scraper.job_slug(job)).name,
                         "69675292_it-manager-dempsey-resource-management-philippines.json")

    def test_pages_through_the_results_and_saves_one_file_per_job(self):
        pages = {0: [search_item(i) for i in range(1, 21)], 20: [search_item(21), search_item(22)]}
        searched = []

        def page(session, query, limit, start, countries):
            searched.append(start)
            return {"data": pages.get(start, []), "meta": {"paging": {"total": 22}}}

        with mock.patch.object(foundit_scraper, "fetch_search_page", side_effect=page), \
                mock.patch.object(foundit_scraper, "fetch_job_detail", side_effect=lambda s, jid: detail(jid)), \
                mock.patch.object(foundit_scraper, "random_delay"):
            foundit_scraper.scrape("computer science", 100, self.tmp, 0, 0, None, None)
        self.assertEqual(searched, [0, 20])               # 20 a page, whatever --limit asks for
        self.assertEqual(len(list(self.tmp.glob("*.json"))), 22)
        saved = json.loads((self.tmp / "21_it-manager-co-philippines.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["jobId"], 21)              # the jobDetail response, saved as-is

    def test_an_empty_answer_is_a_failed_save(self):
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {}
        session = mock.Mock()
        session.get.return_value = resp
        self.assertIsNone(foundit_scraper.fetch_job_detail(session, 1))
        self.assertIn("no job for this ID", foundit_scraper.LAST_ERROR)

        jobs = [search_item(1), search_item(2)]
        foundit_scraper.LAST_ERROR = "foundit returned no job for this ID"
        with mock.patch.object(foundit_scraper, "fetch_search_page",
                               return_value={"data": jobs, "meta": {"paging": {"total": 2}}}), \
                mock.patch.object(foundit_scraper, "fetch_job_detail",
                                  side_effect=lambda s, jid: detail(jid) if jid == 1 else None), \
                mock.patch.object(foundit_scraper, "random_delay"):
            foundit_scraper.scrape("x", 20, self.tmp / "jsons", 0, 0, None, None, report_dir=self.tmp / "run")
        with open(self.tmp / "run" / "foundit_events.csv", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual([r["status"] for r in rows], ["saved", "failed"])
        self.assertEqual(rows[1]["job_id"], "2")
        self.assertIn("no job for this ID", rows[1]["reason"])
        self.assertTrue(rows[1]["url"].startswith("https://www.foundit.com.ph/job/"))

    def test_runs_as_a_script(self):
        out = subprocess.run([sys.executable, str(Path(foundit_scraper.__file__)), "--help"],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("--query", out.stdout)


class FounditCompileTests(TmpDirMixin, TestCase):
    def test_row(self):
        row = compiler.extract_foundit_row(detail(), self.tmp / "x.json")
        self.assertEqual(row["job_id"], 69675292)
        self.assertEqual(row["job_title"], "IT Manager")
        self.assertEqual(row["job_url"], "https://www.foundit.com.ph/job/"
                                         "it-manager-dempsey-resource-management-philippines-69675292")
        self.assertEqual(row["company_name"], "Dempsey Resource Management")
        self.assertEqual(row["city"], "Pasig")
        self.assertEqual(row["months_work_experience"], 60)
        self.assertEqual(row["skills"], "Computer Science; ERP systems")
        self.assertEqual(row["description"], "WORK LOCATION\nPASIG CITY\n- ERP systems")
        # no salary given -> blank salary, not 0
        self.assertFalse(row["salary_shown"])
        self.assertEqual(row["base_salary"], "")

    def test_created_at_is_the_date_in_philippine_time(self):
        # 1793471080000 ms = 2026-10-31 18:24:40 UTC = Nov 1, 02:24:40 in Manila
        row = compiler.extract_foundit_row(detail(), self.tmp / "x.json")
        self.assertEqual(row["created_at"], "2026-11-01T02:24:40+08:00")
        self.assertEqual(row["closed_at"], "2026-12-15T02:30:00+08:00")
        self.assertEqual(normalize_record({"created_at": row["created_at"]})["date"], "2026-11-01T02:24:40+08:00")

    def test_salary_and_hidden_salary(self):
        paid = {"currency": "PHP", "absoluteValue": 600000, "absoluteMonthlyValue": 50000}
        row = compiler.extract_foundit_row(detail(minimumSalary=paid, maximumSalary=paid), self.tmp / "x.json")
        self.assertTrue(row["salary_shown"])
        self.assertEqual((row["base_salary"], row["salary_currency"], row["salary_interval"]), (50000, "PHP", "month"))
        row = compiler.extract_foundit_row(detail(minimumSalary=paid, hideSalary=1), self.tmp / "x.json")
        self.assertFalse(row["salary_shown"])
        self.assertEqual(row["base_salary"], "")

    def test_not_a_foundit_file_is_skipped(self):
        self.assertIsNone(compiler.extract_foundit_row({}, self.tmp / "x.json"))
        self.assertIsNone(compiler.extract_foundit_row({"job_id": "1", "title": "Trabajo job"}, self.tmp / "x.json"))

    def test_compile_script(self):
        jsons = self.tmp / "jsons"
        jsons.mkdir()
        for jid in (1, 2):
            (jsons / f"{jid}_x.json").write_text(json.dumps(detail(jid)), encoding="utf-8")
        out = subprocess.run([sys.executable, str(Path(compiler.__file__)), "--source=foundit",
                              f"--input-dir={jsons}", f"--output-csv={self.tmp / 'compiled_foundit.csv'}"],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        with open(self.tmp / "compiled_foundit.csv", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual([r["job_id"] for r in rows], ["1", "2"])
        self.assertEqual(list(rows[0]), compiler.FOUNDIT_FIELDNAMES)

    def test_extraction_reads_columns_the_compiled_csv_has(self):
        cfg = SOURCE_CONFIG["foundit"]
        for col in cfg["text_columns"] + cfg["company_cols"] + cfg["job_cols"]:
            self.assertIn(col, compiler.FOUNDIT_FIELDNAMES)


class FounditInSystemTests(IsolatedDataMixin, TestCase):
    def test_registered_as_a_source(self):
        self.assertIn("foundit", pipeline.SOURCES)
        self.assertEqual(pipeline.SOURCE_LABELS["foundit"], "Foundit")
        self.assertIn("foundit", pipeline.TABLES)
        self.assertIn("json_foundit", pipeline.IMPORT_TYPES)
        argv = sources.BY_KEY["foundit"].scrape_argv("py", Path("p"), "Data Analyst", Path("o"), 1, 2, 5, "r")
        self.assertEqual(argv[2:], [str(Path("p") / "foundit_scraper.py"), "--query=Data Analyst",
                                    "--output-dir=o", "--delay-min=1", "--delay-max=2", "--max-jobs=5",
                                    "--report-dir=r"])

    def test_run_steps(self):
        cfg = {**pipeline.get_extraction_settings(), "sources": ["foundit"], "searches": ["Data Analyst"],
               "do_scrape": True, "do_compile": True, "do_extract": False, "do_ghost": False}
        names = [s["name"] for s in pipeline.build_steps(cfg)]
        self.assertTrue(names[0].startswith("scrape_foundit"))
        self.assertIn("compile_foundit", names)

    def test_import_json(self):
        good = SimpleUploadedFile("a.json", json.dumps(detail()).encode())
        bad = SimpleUploadedFile("b.json", json.dumps({"job_id": "1-abc", "title": "x"}).encode())
        res = pipeline.import_json_files("foundit", [good, bad], overwrite=False)
        self.assertEqual((res["added"], res["invalid"]), (1, 1))
        self.assertTrue((pipeline.json_dir("foundit")
                         / "69675292_it-manager-dempsey-resource-management-philippines.json").is_file())
