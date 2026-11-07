"""kalibrr_backfill.py: older Kalibrr tech jobs, found by walking job IDs."""
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from ..pipeline import kalibrr_backfill as kb, kalibrr_scraper as ks

JOBS = {   # job_id -> (company_code, slug, createdAt)
    105: ("acme", "senior-software-engineer", "2025-03-01T00:00:00+00:00"),
    104: ("acme", "accounting-staff", "2025-03-01T00:00:00+00:00"),
    102: ("beta", "it-support-specialist", "2023-12-20T00:00:00+00:00"),
    101: ("beta", "data-analyst", "2024-01-05T00:00:00+00:00"),
}


def fake_get(url, **kw):
    job_id = int(url.split("/jobs/")[1].split("/")[0])
    resp = mock.Mock()
    if job_id not in JOBS:
        resp.status_code = 404
        return resp
    code, slug, _ = JOBS[job_id]
    resp.status_code = 200
    resp.json.return_value = {"pageProps": {"__N_REDIRECT": f"/c/{code}/jobs/{job_id}/{slug}",
                                            "__N_REDIRECT_STATUS": 301}}
    return resp


def fake_detail(session, build_id, code, job_id, slug):
    return {"pageProps": {"isExpired": True, "job": {"id": job_id, "slug": slug, "name": slug,
                                                     "createdAt": JOBS[job_id][2], "company": {"code": code}}}}


class KalibrrBackfillTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_backfill(self, **kw):
        session = mock.Mock()
        session.get.side_effect = fake_get
        with mock.patch.object(ks, "build_session", return_value=session), \
                mock.patch.object(ks, "random_delay"), \
                mock.patch.object(ks, "discover_build_id", return_value="b1"), \
                mock.patch.object(ks, "fetch_job_detail", side_effect=fake_detail) as detail:
            n = kb.backfill(100, 105, self.tmp / "jsons", 0, 0, **kw)
        return n, detail, session

    def test_saves_tech_jobs_since_the_cutoff_and_skips_the_rest(self):
        n, detail, session = self.run_backfill()
        self.assertEqual(sorted(p.name for p in (self.tmp / "jsons").glob("*.json")),
                         ["101_data-analyst.json", "105_senior-software-engineer.json"])
        # the accounting job never gets a detail request; the 2023 IT job is fetched but not saved
        self.assertEqual(sorted(c.args[3] for c in detail.call_args_list), [101, 102, 105])
        self.assertEqual((n["saved"], n["not_tech"], n["too_old"], n["missing"]), (2, 1, 1, 2))
        saved = json.loads((self.tmp / "jsons" / "105_senior-software-engineer.json").read_text())
        self.assertTrue(saved["pageProps"]["isExpired"])        # compiled like any Kalibrr job file

    def test_resumes_and_skips_ids_it_already_has(self):
        (self.tmp / "jsons").mkdir()
        (self.tmp / "jsons" / "105_senior-software-engineer.json").write_text("{}")
        n, detail, session = self.run_backfill()
        self.assertEqual(n["existing"], 1)
        self.assertNotIn(105, [int(c.args[0].split("/jobs/")[1].split("/")[0])
                               for c in session.get.call_args_list])
        # a second run starts below the lowest ID checked, so it asks for nothing
        n, detail, session = self.run_backfill()
        self.assertEqual(session.get.call_count, 0)

    def test_tech_slug(self):
        self.assertTrue(kb.is_tech_slug("junior-web-developer"))
        self.assertTrue(kb.is_tech_slug("it-helpdesk-support"))
        self.assertFalse(kb.is_tech_slug("sales-associate"))
