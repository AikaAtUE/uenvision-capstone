"""The failed saves log: job postings a scrape found but couldn't save, one downloadable CSV per
run, named <source>_S<saved>_F<failed>_..._<date>_<time>.csv with only the sources that had a
failed save."""
import csv
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from ..models import CustomUser
from ..pipeline import failed_saves, kalibrr_scraper, manager as pipeline, trabajo_scraper
from .helpers import IsolatedDataMixin


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class TmpDirMixin:
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)


class ReportTests(TmpDirMixin, TestCase):
    def record(self, source, search, saved=0, failed=0):
        r = failed_saves.Recorder(self.tmp / "run", source, search)
        for i in range(saved):
            r.saved(f"{source}-ok-{i}", "Job", "Co", f"https://x/{i}")
        for i in range(failed):
            r.failed("HTTP 500 after 3 attempts", f"{source}-bad-{i}", f"Bad job {i}", "Co", f"https://x/bad{i}")

    def test_name_has_the_counts_of_each_source_with_a_failed_save(self):
        self.record("kalibrr", "Software Engineer", saved=100, failed=2)
        self.record("kalibrr", "Data Analyst", saved=20, failed=1)
        self.record("trabajo", "Software Engineer", saved=80, failed=5)
        path = failed_saves.build_report(self.tmp / "run", self.tmp / "out", "2026-11-06_2130",
                                         order=("kalibrr", "trabajo"))
        self.assertEqual(path.name, "kalibrr_S120_F3_trabajo_S80_F5_2026-11-06_2130.csv")
        rows = read_csv(path)
        self.assertEqual(len(rows), 8)
        self.assertEqual(list(rows[0]), failed_saves.REPORT_FIELDS)
        self.assertEqual(rows[0]["source"], "kalibrr")
        self.assertEqual(rows[0]["search"], "Software Engineer")
        self.assertEqual(rows[0]["reason"], "HTTP 500 after 3 attempts")
        self.assertEqual({r["source"] for r in rows[3:]}, {"trabajo"})

    def test_a_source_with_no_failed_saves_is_left_out(self):
        self.record("kalibrr", "Software Engineer", saved=50)
        self.record("trabajo", "Software Engineer", saved=10, failed=4)
        path = failed_saves.build_report(self.tmp / "run", self.tmp / "out", "2026-11-06_2130",
                                         order=("kalibrr", "trabajo"))
        self.assertEqual(path.name, "trabajo_S10_F4_2026-11-06_2130.csv")
        self.assertEqual({r["source"] for r in read_csv(path)}, {"trabajo"})

    def test_no_file_when_everything_saved_and_built_only_once(self):
        self.record("kalibrr", "Software Engineer", saved=5)
        self.assertIsNone(failed_saves.build_report(self.tmp / "run", self.tmp / "out", "2026-11-06_2130"))
        self.assertFalse((self.tmp / "out").exists())
        self.assertEqual(failed_saves.report_of(self.tmp / "run"), "")
        self.record("kalibrr", "Software Engineer", failed=1)        # the run was stopped after it ended
        self.assertIsNone(failed_saves.build_report(self.tmp / "run", self.tmp / "out", "2026-11-06_2130"))

    def test_two_runs_in_the_same_minute_keep_both_files(self):
        for run in ("run", "run2"):
            failed_saves.Recorder(self.tmp / run, "kalibrr", "x").failed("404")
        a = failed_saves.build_report(self.tmp / "run", self.tmp / "out", "2026-11-06_2130")
        b = failed_saves.build_report(self.tmp / "run2", self.tmp / "out", "2026-11-06_2130")
        self.assertNotEqual(a, b)
        self.assertEqual(sorted(r["name"] for r in failed_saves.list_reports(self.tmp / "out")),
                         sorted([a.name, b.name]))

    def test_only_log_files_can_be_downloaded(self):
        self.record("kalibrr", "x", failed=1)
        path = failed_saves.build_report(self.tmp / "run", self.tmp / "out", "2026-11-06_2130")
        self.assertEqual(failed_saves.safe_report_path(self.tmp / "out", path.name), path)
        for bad in ("../db.sqlite3", "kalibrr_events.csv", "x.csv", ""):
            self.assertIsNone(failed_saves.safe_report_path(self.tmp / "out", bad))

    def test_without_a_report_dir_nothing_is_written(self):
        failed_saves.Recorder(None, "kalibrr", "x").failed("404")      # the scrapers run on their own
        self.assertEqual(list(self.tmp.iterdir()), [])


class KalibrrRecordsFailuresTests(TmpDirMixin, TestCase):
    def test_each_failed_posting_is_recorded_with_why(self):
        jobs = [{"id": 1, "slug": "dev", "name": "Developer", "company": {"code": "acme", "name": "Acme"}},
                {"id": 2, "slug": "qa", "name": "QA Tester", "company": {"code": "acme", "name": "Acme"}},
                {"id": 3, "slug": "", "name": "No slug", "company": {"code": "acme", "name": "Acme"}}]

        def detail(session, build_id, company_code, job_id, slug):
            if job_id == 2:
                kalibrr_scraper.LAST_ERROR = "HTTP 500 after 3 attempts"
                return None
            return {"id": job_id}

        with mock.patch.object(kalibrr_scraper, "fetch_search_page", return_value={"count": 3, "jobs": jobs}), \
                mock.patch.object(kalibrr_scraper, "fetch_job_detail", side_effect=detail), \
                mock.patch.object(kalibrr_scraper, "random_delay"):
            kalibrr_scraper.scrape("Software Engineer", 100, self.tmp / "jsons", 0, 0, "build",
                                   None, None, report_dir=self.tmp / "run")
        path = failed_saves.build_report(self.tmp / "run", self.tmp / "out", "2026-11-06_2130")
        self.assertEqual(path.name, "kalibrr_S1_F2_2026-11-06_2130.csv")
        rows = read_csv(path)
        self.assertEqual(rows[0]["job_id"], "2")
        self.assertEqual(rows[0]["title"], "QA Tester")
        self.assertEqual(rows[0]["company"], "Acme")
        self.assertEqual(rows[0]["url"], "https://www.kalibrr.com/c/acme/jobs/2/qa")
        self.assertIn("HTTP 500", rows[0]["reason"])
        self.assertEqual(rows[0]["search"], "Software Engineer")
        self.assertIn("no slug", rows[1]["reason"])


class TrabajoRecordsFailuresTests(TmpDirMixin, TestCase):
    def test_fetch_and_parse_failures_are_recorded(self):
        base = "https://ph.trabajo.org/job-"
        jobs = [{"url": f"{base}1-aaaaaaaa", "title": "Developer", "company": "Acme", "data_id": "1"},
                {"url": f"{base}2-bbbbbbbb", "title": "Analyst", "company": "Beta", "data_id": "2"},
                {"url": f"{base}3-cccccccc", "title": "Admin", "company": "Gamma", "data_id": "3"}]

        def get_html(self, url):
            if url.endswith("bbbbbbbb"):
                self.last_error = "HTTP 503 after 3 attempts"
                return None
            return "<html></html>"

        def parse(html, url):
            if url.endswith("cccccccc"):
                raise ValueError("no title")
            return {"title": "Developer"}

        with mock.patch.object(trabajo_scraper.Fetcher, "get_html", get_html), \
                mock.patch.object(trabajo_scraper, "load_robots", return_value=None), \
                mock.patch.object(trabajo_scraper, "parse_listing_page", return_value={"jobs": jobs, "next_url": None}), \
                mock.patch.object(trabajo_scraper, "parse_job_detail", side_effect=parse), \
                mock.patch.object(trabajo_scraper, "random_delay"):
            trabajo_scraper.scrape("Software Engineer", self.tmp / "jsons", 0, 0, None, None, 1, 5,
                                   report_dir=self.tmp / "run")
        path = failed_saves.build_report(self.tmp / "run", self.tmp / "out", "2026-11-06_2130")
        self.assertEqual(path.name, "trabajo_S1_F2_2026-11-06_2130.csv")
        rows = read_csv(path)
        self.assertEqual([r["title"] for r in rows], ["Analyst", "Admin"])
        self.assertIn("HTTP 503", rows[0]["reason"])
        self.assertIn("Couldn't read the job page", rows[1]["reason"])
        self.assertEqual(rows[1]["url"], f"{base}3-cccccccc")


class RunWritesTheLogTests(IsolatedDataMixin, TestCase):
    def test_scrape_steps_get_the_report_dir(self):
        steps = pipeline.build_steps({"sources": ["kalibrr", "trabajo"], "do_scrape": True,
                                      "searches": ["Software Engineer"], "delay_min": 1, "delay_max": 2})
        for s in steps:
            self.assertIn(f"--report-dir={pipeline.failed_saves_run_dir()}", s["argv"])

    def test_the_orchestrator_builds_the_log_when_the_run_ends(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        py, run_dir, out_dir = sys.executable, tmp / "run", tmp / "out"
        code = ("import sys; sys.path.insert(0, %r); import failed_saves as f; "
                "r = f.Recorder(%r, 'kalibrr', 'Software Engineer'); r.saved('1'); r.failed('HTTP 404', '2'); "
                "sys.exit(1)") % (str(pipeline.PIPELINE_DIR), str(run_dir))
        steps = [{"name": "s", "label": "s", "lane": "kalibrr", "continue_on_fail": True, "argv": [py, "-c", code]},
                 {"name": "x", "label": "x", "argv": [py, "-c", "import sys; sys.exit(2)"]}]   # a failed step
        state = {"status": "running", "steps": [{"name": s["name"], "label": s["label"], "status": "pending"}
                                                for s in steps]}
        (tmp / "run.json").write_text(json.dumps(state))
        (tmp / "run.log").write_text("")
        cfg = {"state_file": str(tmp / "run.json"), "log_file": str(tmp / "run.log"), "cwd": str(tmp),
               "steps": steps, "lane_labels": {},
               "finish_argv": [py, "-u", str(Path(pipeline.PIPELINE_DIR) / "failed_saves.py"),
                               str(run_dir), str(out_dir), "2026-11-06_2130", "kalibrr", "trabajo"]}
        (tmp / "cfg.json").write_text(json.dumps(cfg))
        subprocess.run([py, str(Path(pipeline.PIPELINE_DIR) / "orchestrator.py"), str(tmp / "cfg.json")],
                       check=True, timeout=60)
        self.assertTrue((out_dir / "kalibrr_S1_F1_2026-11-06_2130.csv").is_file())
        self.assertIn("Failed saves log: kalibrr_S1_F1_2026-11-06_2130.csv", (tmp / "run.log").read_text())

    def test_start_run_passes_the_finish_command(self):
        cfg = {"sources": ["kalibrr"], "do_scrape": True, "searches": ["Software Engineer"],
               "delay_min": 1, "delay_max": 2}
        with mock.patch.object(pipeline.subprocess, "Popen") as popen:
            popen.return_value.pid = 4321
            self.assertIsNone(pipeline.start_run(cfg))
        run_cfg = json.loads((pipeline.state_dir() / "run_config.json").read_text())
        self.assertEqual(run_cfg["finish_argv"][3:5], [str(pipeline.failed_saves_run_dir()),
                                                       str(pipeline.failed_saves_dir())])
        self.assertTrue(pipeline.failed_saves_run_dir().is_dir())
        self.assertTrue(pipeline.get_run_state()["failed_saves_stamp"])

    def test_stopping_a_run_still_writes_the_log(self):
        cfg = {"sources": ["kalibrr"], "do_scrape": True, "searches": ["Software Engineer"],
               "delay_min": 1, "delay_max": 2}
        with mock.patch.object(pipeline.subprocess, "Popen") as popen:
            popen.return_value.pid = 999999
            pipeline.start_run(cfg)
        failed_saves.Recorder(pipeline.failed_saves_run_dir(), "kalibrr", "x").failed("HTTP 404", "7")
        with mock.patch.object(pipeline.os, "killpg", create=True), \
                mock.patch.object(pipeline.subprocess, "run"):
            self.assertTrue(pipeline.stop_run())
        name = pipeline.last_failed_saves_report()
        self.assertRegex(name, r"^kalibrr_S0_F1_\d{4}-\d{2}-\d{2}_\d{4}\.csv$")
        self.assertTrue((pipeline.failed_saves_dir() / name).is_file())


class DownloadTests(IsolatedDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = CustomUser.objects.create_user(email="adm@ue.edu.ph", password="secret123", first_name="A",
                                                    last_name="B", role=CustomUser.Role.ADMINISTRATOR)
        self.client.force_login(self.admin)
        pipeline.ensure_dirs()
        rec = failed_saves.Recorder(pipeline.failed_saves_run_dir(), "trabajo", "Software Engineer")
        rec.saved("1")
        rec.failed("HTTP 503 after 3 attempts", "2", "Analyst", "Beta", "https://ph.trabajo.org/job-2-bbbbbbbb")
        self.path = pipeline.build_failed_saves_report("2026-11-06_2130")

    def test_the_page_lists_the_logs_with_download_links(self):
        page = self.client.get(reverse("data_extraction"))
        self.assertContains(page, '<details class="dx-sub" id="failed-saves"')
        self.assertContains(page, "Failed save lists")
        self.assertContains(page, "Nov 6, 2026 · 9:30 PM")
        self.assertContains(page, f'name="name" value="{self.path.name}"')
        self.assertContains(page, 'id="failed-saves-delete-form"')
        url = reverse("failed_saves_download", args=[self.path.name])
        self.assertContains(page, f'href="{url}"')
        self.assertContains(page, "Trabajo: 1 saved, 1 failed")

    def test_every_list_is_shown_latest_run_first(self):
        for stamp in ("2026-10-01_0200", "2026-11-07_0200", "2026-09-15_0200"):
            failed_saves.Recorder(pipeline.state_dir() / stamp, "kalibrr", "x").failed("404")
            failed_saves.build_report(pipeline.state_dir() / stamp, pipeline.failed_saves_dir(), stamp)
        for i in range(12):
            failed_saves.Recorder(pipeline.state_dir() / f"r{i}", "kalibrr", "x").failed("404")
            failed_saves.build_report(pipeline.state_dir() / f"r{i}", pipeline.failed_saves_dir(), "2025-01-01_0000")
        names = [r["name"] for r in pipeline.list_failed_saves()]
        self.assertEqual(len(names), 16)
        self.assertEqual(names[:3], ["kalibrr_S0_F1_2026-11-07_0200.csv", self.path.name,
                                     "kalibrr_S0_F1_2026-10-01_0200.csv"])
        self.assertEqual(names[4], "kalibrr_S0_F1_2025-01-01_0000-12.csv")
        page = self.client.get(reverse("data_extraction"))
        self.assertContains(page, "16 files")
        self.assertEqual(page.content.decode().count('class="btn btn-ghost btn-sm dx-failed-delete"'), 16)

    def test_delete(self):
        url = reverse("failed_saves_delete")
        self.assertEqual(self.client.get(url).status_code, 405)
        r = self.client.post(url, {"name": self.path.name}, HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(r.json(), {"ok": True, "error": None, "count": 0, "latest": ""})
        self.assertFalse(self.path.exists())
        r = self.client.post(url, {"name": self.path.name}, HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(r.status_code, 400)
        self.assertIn("doesn't exist", r.json()["error"])

    def test_delete_without_javascript_redirects(self):
        r = self.client.post(reverse("failed_saves_delete"), {"name": self.path.name})
        self.assertRedirects(r, reverse("data_extraction") + "#scrape", fetch_redirect_response=False)
        self.assertFalse(self.path.exists())

    def test_delete_cannot_reach_other_files(self):
        (pipeline.data_dir() / "keep.csv").write_text("x")
        for bad in ("../keep.csv", "keep.csv", "../.state/run.json", ""):
            r = self.client.post(reverse("failed_saves_delete"), {"name": bad}, HTTP_X_REQUESTED_WITH="fetch")
            self.assertEqual(r.status_code, 400)
        self.assertTrue((pipeline.data_dir() / "keep.csv").exists())

    def test_only_administrators_delete(self):
        faculty = CustomUser.objects.create_user(email="fac2@ue.edu.ph", password="secret123", first_name="F",
                                                 last_name="G", role=CustomUser.Role.FACULTY)
        self.client.force_login(faculty)
        self.client.post(reverse("failed_saves_delete"), {"name": self.path.name})
        self.assertTrue(self.path.exists())

    def test_download(self):
        r = self.client.get(reverse("failed_saves_download", args=[self.path.name]))
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r["Content-Disposition"])
        body = b"".join(r.streaming_content).decode("utf-8-sig")
        self.assertIn("HTTP 503 after 3 attempts", body)
        self.assertEqual(self.client.get(reverse("failed_saves_download", args=["db.sqlite3"])).status_code, 404)

    def test_only_administrators_download(self):
        faculty = CustomUser.objects.create_user(email="fac@ue.edu.ph", password="secret123", first_name="F",
                                                 last_name="G", role=CustomUser.Role.FACULTY)
        self.client.force_login(faculty)
        r = self.client.get(reverse("failed_saves_download", args=[self.path.name]))
        self.assertNotEqual(r.status_code, 200)

    def test_console_status_links_the_finished_runs_log(self):
        state = {"status": "done", "failed_saves_stamp": "2026-11-06_2130", "steps": []}
        pipeline._atomic_write_text(pipeline.state_dir() / "run.json", json.dumps(state))
        d = self.client.get(reverse("scrape_status")).json()
        self.assertEqual(d["failed_saves"]["name"], self.path.name)
        self.assertEqual(d["failed_saves"]["url"], reverse("failed_saves_download", args=[self.path.name]))
