"""Data -> Data Extraction: Scrape Data / Skill Extraction / Ghost Job Detection / What to run /
Automation on one page, single and multiple search (the CHED roles can't be removed), both job
sources in one run, the parallel source lanes of the orchestrator, and the automatic runs."""
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from ..models import CustomUser
from ..pipeline import manager as pipeline, search_terms
from .helpers import IsolatedDataMixin

CHED = ["Software Engineer", "Systems Software Developer", "Research and Development Computing Professional",
        "Applications Software Developer", "Computer Programmer", "Systems Analyst", "Data Analyst",
        "Quality Assurance Specialist", "Software Support Specialist", "Web and Applications Developer",
        "Junior Database Administrator", "Systems Administrator", "Network Engineer",
        "Junior Information Security Administrator", "Systems Integration Personnel", "IT Audit Assistant",
        "Technical Support Specialist", "QA Specialist"]


def form(**over):
    data = {"sources": ["kalibrr", "trabajo"], "search_mode": "single", "keyword": "computer science",
            "extra_searches": "", "delay_min": "1.5", "delay_max": "4", "max_jobs": "",
            "batch_size": "20", "model": "gemini-3.5-flash-lite",
            "do_scrape": "on", "do_compile": "on", "do_extract": "on", "standardize": "on", "do_ghost": "on",
            "flag_duplicates": "on", "flag_hidden_salary": "on", "flag_unverified": "on",
            "min_description_chars": "500", "weak_signs_needed": "2",
            "auto_frequency": "days", "auto_every_days": "1", "auto_weekdays": ["0"], "auto_time": "02:00"}
    data.update(over)
    return {k: v for k, v in data.items() if v is not None}


class SearchListTests(TestCase):
    def test_ched_roles_are_the_locked_searches(self):
        self.assertEqual(search_terms.default_terms(), CHED)
        tags = {d["term"]: d["tags"] for d in search_terms.default_searches()}
        self.assertEqual(tags["Systems Analyst"], ["BSCS secondary", "BSIT secondary"])
        self.assertEqual(tags["Computer Programmer"], ["BSCS primary", "BSIT secondary"])

    def test_extra_searches_cannot_drop_or_repeat_the_locked_ones(self):
        extra, error = search_terms.parse_extra("DevOps Engineer\n\n  software   engineer \ndevops engineer\nCloud Engineer\r\n")
        self.assertIsNone(error)
        self.assertEqual(extra, ["DevOps Engineer", "Cloud Engineer"])
        full = search_terms.multiple_list(extra)
        self.assertEqual(full[:len(CHED)], CHED)
        self.assertEqual(full[len(CHED):], ["DevOps Engineer", "Cloud Engineer"])
        # even an empty list of extras keeps every CHED role
        self.assertEqual(search_terms.multiple_list([]), CHED)
        self.assertIsNotNone(search_terms.parse_extra("x" * 101)[1])


class DataExtractionPageTests(IsolatedDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = CustomUser.objects.create_user(email="adm@ue.edu.ph", password="secret123", first_name="A",
                                                    last_name="B", role=CustomUser.Role.ADMINISTRATOR)
        self.client.force_login(self.admin)

    def test_one_page_with_collapsible_sections(self):
        page = self.client.get(reverse("data_extraction"))
        self.assertEqual(page.status_code, 200)
        for section in ("Scrape Data", "Skill Extraction", "Ghost Job Detection", "What to run", "Automation"):
            self.assertContains(page, section)
        self.assertContains(page, '<details class="dx-section" id="scrape"')
        self.assertContains(page, '<details class="dx-section" id="automation"')
        for role in CHED:
            self.assertContains(page, f'<span class="dx-term">{role}</span>')
        self.assertContains(page, 'name="sources" value="kalibrr" checked')
        self.assertContains(page, 'name="sources" value="trabajo" checked')
        self.assertContains(page, 'name="do_extract" checked')
        # the tabs: one Data Extraction tab instead of Scrape Data / Extract Skills / Ghost Jobs
        self.assertContains(page, ">Data Extraction</a>")
        self.assertNotContains(page, ">Scrape Data</a>")
        self.assertNotContains(page, ">Ghost Jobs</a>")

    def test_old_addresses_lead_to_the_sections(self):
        self.assertRedirects(self.client.get(reverse("data_scrape")), reverse("data_extraction") + "#scrape",
                             fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse("data_extract")), reverse("data_extraction") + "#skills",
                             fetch_redirect_response=False)

    def test_administrators_only(self):
        faculty = CustomUser.objects.create_user(email="fac@ue.edu.ph", password="secret123", first_name="F",
                                                 last_name="G", role=CustomUser.Role.FACULTY)
        self.client.force_login(faculty)
        self.assertEqual(self.client.get(reverse("data_extraction")).status_code, 403)
        self.assertEqual(self.client.post(reverse("data_extraction"), form(action="run")).status_code, 403)
        self.assertContains(self.client.get(reverse("data")), ">Ghost Jobs</a>")

    def test_save_keeps_every_section(self):
        with mock.patch.object(pipeline, "start_run") as start:
            resp = self.client.post(reverse("data_extraction"), form(
                action="save", search_mode="multiple", extra_searches="DevOps Engineer\nSystems Analyst",
                do_ghost=None, weak_signs_needed="1", auto_enabled="on", auto_time="03:30"))
        self.assertRedirects(resp, reverse("data_extraction"), fetch_redirect_response=False)
        start.assert_not_called()
        cfg = pipeline.get_extraction_settings()
        self.assertEqual(cfg["sources"], ["kalibrr", "trabajo"])
        self.assertEqual(cfg["search_mode"], "multiple")
        self.assertEqual(cfg["extra_searches"], ["DevOps Engineer"])      # a CHED role isn't stored twice
        self.assertFalse(cfg["do_ghost"])
        state = settings.DATA_DIR / ".state"
        self.assertEqual(json.loads((state / "ghost_settings.json").read_text())["weak_signs_needed"], 1)
        auto = json.loads((state / "automation.json").read_text())
        self.assertTrue(auto["enabled"])
        self.assertEqual(auto["time"], "03:30")
        page = self.client.get(reverse("data_extraction"))
        self.assertContains(page, "19 searches in all: 18 from CHED and 1 added.")
        self.assertContains(page, "DevOps Engineer</textarea>")

    def test_run_multiple_search_on_both_sources(self):
        with mock.patch.object(pipeline, "start_run", return_value=None) as start:
            resp = self.client.post(reverse("data_extraction"), form(
                action="run", search_mode="multiple", extra_searches="DevOps Engineer", max_jobs="5"))
        self.assertRedirects(resp, reverse("console"), fetch_redirect_response=False)
        cfg = start.call_args.args[0]
        self.assertEqual(start.call_args.kwargs["kind"], "extraction")
        self.assertEqual(cfg["searches"], CHED + ["DevOps Engineer"])
        steps = pipeline.build_steps(cfg)
        scrapes = [s for s in steps if s["name"].startswith("scrape_")]
        self.assertEqual(len(scrapes), 2 * (len(CHED) + 1))
        self.assertEqual({s["lane"] for s in scrapes}, {"kalibrr", "trabajo"})
        self.assertTrue(all(s["continue_on_fail"] for s in scrapes))
        self.assertIn("--text=Software Engineer", scrapes[0]["argv"])           # Kalibrr's option
        trabajo = [s for s in scrapes if s["lane"] == "trabajo"]
        self.assertIn("--keyword=Software Engineer", trabajo[0]["argv"])      # Trabajo's option
        self.assertIn("--max-jobs=5", trabajo[0]["argv"])
        names = [s["name"] for s in steps if not s["name"].startswith("scrape_")]
        self.assertEqual(names, ["compile_kalibrr", "compile_trabajo", "extract_kalibrr", "extract_trabajo",
                                 "standardize", "ghost"])
        # the scrape + compile steps of each source come before anything that has no lane
        first_plain = next(i for i, s in enumerate(steps) if not s.get("lane"))
        self.assertTrue(all(s.get("lane") for s in steps[:first_plain]))

    def test_single_search_runs_the_one_keyword(self):
        with mock.patch.object(pipeline, "start_run", return_value=None) as start:
            self.client.post(reverse("data_extraction"), form(action="run", sources=["trabajo"],
                                                              keyword="  data   analyst "))
        cfg = start.call_args.args[0]
        self.assertEqual(cfg["searches"], ["data analyst"])
        self.assertEqual([s["label"] for s in pipeline.build_steps(cfg)][:2],
                         ["Scrape Trabajo: “data analyst”", "Compile Trabajo JSONs to CSV"])

    def test_run_needs_a_step_and_a_source(self):
        none = {k: None for k in ("do_scrape", "do_compile", "do_extract", "standardize", "do_ghost")}
        resp = self.client.post(reverse("data_extraction"), form(action="run", **none))
        self.assertContains(resp, "Tick at least one step", status_code=400)
        resp = self.client.post(reverse("data_extraction"), form(action="run", sources=[]))
        self.assertContains(resp, "Tick at least one job source", status_code=400)
        resp = self.client.post(reverse("data_extraction"), form(action="run", keyword=""))
        self.assertContains(resp, "Enter a search keyword", status_code=400)
        # only ghost detection: no source needed
        with mock.patch.object(pipeline, "start_run", return_value=None) as start:
            self.client.post(reverse("data_extraction"), form(action="run", sources=[], **{**none, "do_ghost": "on"}))
        self.assertEqual([s["name"] for s in pipeline.build_steps(start.call_args.args[0])], ["ghost"])

    def test_extraction_in_the_same_run_as_compiling_needs_no_csv_yet(self):
        (settings.DATA_DIR / "api_keys.txt").write_text("AIzaTEST\n")
        cfg = pipeline.run_config({**pipeline.get_extraction_settings(), "do_scrape": True, "do_compile": True,
                                   "do_extract": True})
        with self.settings(API_KEYS_FILE=settings.DATA_DIR / "api_keys.txt"), \
                mock.patch.object(pipeline.subprocess, "Popen") as popen:
            popen.return_value.pid = 4242
            self.assertIsNone(pipeline.start_run(cfg))
        state = pipeline.get_run_state()
        self.assertEqual(state["kind"], "extraction")
        self.assertEqual(state["source"], "Kalibrr + Trabajo")
        (settings.DATA_DIR / ".state" / "run.json").unlink()
        with self.settings(API_KEYS_FILE=settings.DATA_DIR / "api_keys.txt"):
            self.assertIn("no compiled Kalibrr CSV",
                          pipeline.start_run({**cfg, "do_scrape": False, "do_compile": False}) or "")

    def test_automation_needs_a_source(self):
        resp = self.client.post(reverse("data_extraction"), form(action="save", sources=[], auto_enabled="on"))
        self.assertContains(resp, "Automation: Tick at least one job source", status_code=400)

    def test_enter_key_saves_instead_of_running_or_saving_only_the_keys(self):
        page = self.client.get(reverse("data_extraction")).content.decode()
        form_html = page[page.index('id="extraction-form"'):page.index("</form>", page.index('id="extraction-form"'))]
        first_button = form_html[form_html.index("<button"):form_html.index("</button>")]
        self.assertIn('value="save"', first_button)       # Enter in a field = Save settings
        self.assertIn('form="api-keys-form"', page)
        self.assertNotIn("formaction=", page)

    def test_save_automation_returns_to_its_section(self):
        resp = self.client.post(reverse("data_extraction"), form(action="save-automation", auto_enabled="on"))
        self.assertRedirects(resp, reverse("data_extraction") + "#automation", fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("data_extraction")), "Automation saved: on, every day at 2:00 AM.")

    def test_api_keys_button_returns_to_the_page(self):
        with self.settings(API_KEYS_FILE=settings.DATA_DIR / "keys.txt"):
            resp = self.client.post(reverse("api_keys_save"), form(keys="AIzaONE\nAIzaTWO"))
            self.assertRedirects(resp, reverse("data_extraction") + "#skills", fetch_redirect_response=False)
            self.assertEqual(pipeline.count_api_keys(), 2)

    def test_ghost_job_check_command(self):
        out = StringIO()
        call_command("ghost_job_check", stdout=out)
        self.assertIn("marked as possible ghost jobs", out.getvalue())


class AutomationTests(IsolatedDataMixin, TestCase):
    def at(self, day, hh=0, mm=0):
        from .. import automation
        return datetime(2026, 11, day, hh, mm, tzinfo=automation.tz())

    def save(self, **over):
        from .. import automation
        cfg = {**automation.DEFAULT_SETTINGS, "enabled": True, **over}
        with mock.patch.object(automation, "now", return_value=self.at(6, 10)):   # Fri Nov 6, 10:00 AM
            automation.save_settings(cfg)
        return cfg

    def test_every_n_days(self):
        from .. import automation
        cfg = self.save(every_days=3, time="02:00")
        self.assertEqual(automation.get_state()["next_run"], self.at(7, 2).isoformat())  # 2 AM already passed today
        nxt = automation.following_run(cfg, self.at(7, 2), self.at(7, 2, 1))
        self.assertEqual(nxt, self.at(10, 2))
        # the server was off for a week: one catch-up run, then back on the 3-day rhythm
        self.assertEqual(automation.following_run(cfg, self.at(7, 2), self.at(14, 9)), self.at(16, 2))

    def test_days_of_the_week(self):
        from .. import automation
        cfg = self.save(frequency="weekdays", weekdays=[0, 3], time="22:15")   # Mon and Thu
        self.assertEqual(automation.get_state()["next_run"], self.at(9, 22, 15).isoformat())
        self.assertEqual(automation.following_run(cfg, self.at(9, 22, 15), self.at(9, 22, 16)), self.at(12, 22, 15))
        self.assertEqual(automation.describe(cfg), "every Monday and Thursday at 10:15 PM")

    def test_tick_runs_everything_with_the_multiple_list(self):
        from .. import automation
        pipeline.save_extraction_settings({**pipeline.get_extraction_settings(), "search_mode": "single",
                                           "keyword": "x", "extra_searches": ["Cloud Engineer"],
                                           "do_extract": False, "do_ghost": False, "sources": ["trabajo"]})
        self.save(time="02:00")
        with mock.patch.object(pipeline, "start_run", return_value=None) as start:
            self.assertIn("Not due", automation.tick(self.at(7, 1, 55)))
            start.assert_not_called()
            automation.tick(self.at(7, 2, 0))
        cfg = start.call_args.args[0]
        self.assertEqual(start.call_args.kwargs["kind"], "automation")
        self.assertEqual(cfg["searches"], CHED + ["Cloud Engineer"])   # multiple list, though the switch says single
        self.assertEqual(cfg["sources"], ["trabajo"])
        self.assertTrue(all(cfg[k] for k in ("do_scrape", "do_compile", "do_extract", "do_standardize", "do_ghost")))
        state = automation.get_state()
        self.assertEqual(state["next_run"], self.at(8, 2).isoformat())
        self.assertEqual(state["last_run"], self.at(7, 2).isoformat())

    def test_tick_waits_for_a_run_in_progress_and_skips_when_off(self):
        from .. import automation
        self.save(time="02:00")
        with mock.patch.object(pipeline, "is_running", return_value=True), \
                mock.patch.object(pipeline, "start_run") as start:
            self.assertIn("already in progress", automation.tick(self.at(7, 2, 5)))
            start.assert_not_called()
        self.assertEqual(automation.get_state()["next_run"], self.at(7, 2).isoformat())   # tried again next check
        self.save(enabled=False)
        with mock.patch.object(pipeline, "start_run", return_value=None) as start:
            self.assertEqual(automation.tick(self.at(7, 3)), "Automation is off.")
            start.assert_not_called()
            automation.tick(self.at(7, 3), force=True)       # manage.py run_automation --now
            start.assert_called_once()

    def test_page_shows_the_schedule_and_scheduler_state(self):
        from .. import automation
        admin = CustomUser.objects.create_user(email="adm@ue.edu.ph", password="secret123", first_name="A",
                                               last_name="B", role=CustomUser.Role.ADMINISTRATOR)
        self.client.force_login(admin)
        self.save(time="02:00")
        page = self.client.get(reverse("data_extraction"))
        self.assertContains(page, "every day at 2:00 AM")
        self.assertContains(page, "Sat, Nov 7, 2026 · 2:00 AM")
        self.assertContains(page, "Not running here")
        with mock.patch.object(pipeline, "start_run", return_value=None):
            automation.tick(automation.now(), wait=False)
        self.assertContains(self.client.get(reverse("data_extraction")), "last checked just now")


class OrchestratorLaneTests(TestCase):
    """orchestrator.py runs each source's steps as a lane, the lanes at the same time."""

    def test_lanes_run_together_and_a_failed_search_does_not_stop_its_lane(self):
        tmp = Path(tempfile.mkdtemp())
        py = sys.executable

        def step(name, lane, code, **extra):
            return {"name": name, "label": name, "lane": lane, "argv": [py, "-c", code], **extra}

        steps = [
            step("a1", "kalibrr", "import time; time.sleep(1.2); print('kalibrr one')"),
            step("a2", "kalibrr", "import sys; print('boom'); sys.exit(3)", continue_on_fail=True),
            step("a3", "kalibrr", "print('kalibrr three')"),
            step("b1", "trabajo", "import time; time.sleep(1.2); print('trabajo one')"),
            {"name": "after", "label": "after", "argv": [py, "-c", "print('after lanes')"]},
        ]
        state = {"status": "running", "steps": [{"name": s["name"], "label": s["label"], "status": "pending"}
                                                for s in steps]}
        (tmp / "run.json").write_text(json.dumps(state))
        (tmp / "run.log").write_text("")
        cfg = {"state_file": str(tmp / "run.json"), "log_file": str(tmp / "run.log"), "cwd": str(tmp),
               "steps": steps, "lane_labels": {"kalibrr": "Kalibrr", "trabajo": "Trabajo"}}
        (tmp / "cfg.json").write_text(json.dumps(cfg))
        started = datetime.now()
        subprocess.run([py, str(Path(pipeline.PIPELINE_DIR) / "orchestrator.py"), str(tmp / "cfg.json")],
                       check=True, timeout=60)
        took = datetime.now() - started
        result = json.loads((tmp / "run.json").read_text())
        self.assertEqual([s["status"] for s in result["steps"]], ["done", "failed", "done", "done", "done"])
        self.assertEqual(result["status"], "failed")       # a search failed, but everything ran
        log = (tmp / "run.log").read_text()
        self.assertIn("[Kalibrr] kalibrr one", log)
        self.assertIn("[Trabajo] trabajo one", log)
        self.assertIn("going on with the next one", log)
        self.assertIn("after lanes", log)
        self.assertLess(took, timedelta(seconds=2.3))      # the two 1.2 s steps ran side by side
