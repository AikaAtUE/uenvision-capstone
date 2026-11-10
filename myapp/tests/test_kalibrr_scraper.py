"""kalibrr_scraper.py: the search needs no build id; job details look it up when needed."""
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from ..pipeline import kalibrr_scraper as ks

# The search API's answer (kjs/job_board/search), cut down to the fields the scraper reads.
SEARCH = {"count": 2, "search_text": "quality assurance", "jobs": [
    {"id": 270006, "slug": "quality-assurance-specialist-2", "name": "Quality Assurance Specialist",
     "company": {"code": "multisys-technologies-corporation", "name": "Multisys Technologies Corporation"}},
    {"id": 270007, "slug": "qa-tester", "name": "QA Tester", "company": {"code": "acme", "name": "Acme"}},
]}
JOB_HTML = '<script id="__NEXT_DATA__" type="application/json">{"props":{},"buildId":"%s"}</script>'


def detail_json(job_id, slug, code):
    return {"pageProps": {"job": {"id": job_id, "slug": slug, "name": slug, "company": {"code": code}},
                          "isExpired": False}, "__N_SSG": True}


class FakeKalibrr:
    """Answers like kalibrr.com: `live` is the current build id, `down` the URLs answering 500."""

    def __init__(self, live="NEW", down=(), search_fail=0, detail=None):
        self.live, self.down, self.search_fail = live, set(down), search_fail
        self.detail = detail or {}       # (job_id) -> JSON to answer instead of the job
        self.urls = []

    def get(self, url, headers=None, timeout=None):
        self.urls.append(url)
        resp = mock.Mock(status_code=200, text="")
        if url in self.down:
            resp.status_code = 500
        elif "/kjs/job_board/search" in url:
            if self.search_fail:
                self.search_fail -= 1
                resp.status_code = 503
            else:
                resp.json.return_value = SEARCH
        elif "/_next/data/" in url:
            build = url.split("/_next/data/")[1].split("/")[0]
            job_id = int(url.split("/jobs/")[1].split("/")[0])
            slug = url.split("/jobs/")[1].split("/")[1].split(".json")[0]
            code = url.split("/c/")[1].split("/")[0]
            if build != self.live:
                resp.status_code = 404
            elif job_id in self.detail and not (isinstance(self.detail[job_id], tuple) and slug == self.detail[job_id][1]):
                answer = self.detail[job_id]
                resp.json.return_value = answer if isinstance(answer, dict) else {
                    "pageProps": {"__N_REDIRECT": f"/c/{answer[0]}/jobs/{job_id}/{answer[1]}"}}
            else:
                resp.json.return_value = detail_json(job_id, slug, code)
        else:                            # any Kalibrr HTML page
            resp.text = JOB_HTML % self.live
        return resp


class KalibrrScraperTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = self.tmp / "jsons"

    def scrape(self, site, build_id=None):
        with mock.patch.object(ks, "build_session", return_value=site), \
                mock.patch.object(ks, "random_delay"), mock.patch.object(ks.time, "sleep"):
            ks.scrape("quality assurance", 100, self.out, 0, 0, build_id, None, None)

    def saved(self):
        return sorted(p.name for p in self.out.glob("*.json"))

    def test_search_runs_without_a_build_id_when_nothing_new_needs_details(self):
        self.out.mkdir()
        for job in SEARCH["jobs"]:
            (self.out / f"{job['id']}_{job['slug']}.json").write_text("{}")
        site = FakeKalibrr(down={ks.HOME_URL, "https://www.kalibrr.com/home"})
        self.scrape(site)                # used to stop with "no build_id available"
        self.assertTrue(all("/kjs/job_board/search" in u for u in site.urls))

    def test_build_id_is_read_from_the_job_page_when_the_homepage_is_down(self):
        site = FakeKalibrr(down={ks.HOME_URL, "https://www.kalibrr.com/home"})
        self.scrape(site)
        self.assertEqual(self.saved(), ["270006_quality-assurance-specialist-2.json", "270007_qa-tester.json"])
        self.assertIn("https://www.kalibrr.com/c/multisys-technologies-corporation/jobs/270006/"
                      "quality-assurance-specialist-2", site.urls)
        self.assertEqual((self.out / ks.BUILD_ID_FILE).read_text(), "NEW")
        # looked up once, not once per job
        self.assertEqual(sum("/_next/data/" not in u and "/kjs/" not in u for u in site.urls), 1)

    def test_the_saved_build_id_is_used_when_no_kalibrr_page_loads(self):
        self.out.mkdir()
        (self.out / ks.BUILD_ID_FILE).write_text("NEW")
        job_page = "https://www.kalibrr.com/c/acme/jobs/270007/qa-tester"
        mtk = ("https://www.kalibrr.com/c/multisys-technologies-corporation/jobs/270006/"
               "quality-assurance-specialist-2")
        site = FakeKalibrr(down={*ks.BUILD_ID_PAGES, job_page, mtk})
        self.scrape(site)
        self.assertEqual(len(self.saved()), 2)

    def test_a_stale_build_id_is_looked_up_again_and_the_job_fetched_again(self):
        self.out.mkdir()
        (self.out / ks.BUILD_ID_FILE).write_text("OLD")     # Kalibrr redeployed since the last run
        site = FakeKalibrr(live="NEW")
        self.scrape(site)
        self.assertEqual(len(self.saved()), 2)
        self.assertEqual((self.out / ks.BUILD_ID_FILE).read_text(), "NEW")
        self.assertEqual(sum("/_next/data/OLD/" in u for u in site.urls), 1)   # the 2nd job uses NEW

    def test_redirects_are_followed_and_answers_without_a_job_are_not_saved(self):
        site = FakeKalibrr(detail={270006: ("multisys-technologies-corporation", "qa-specialist-renamed"),
                                   270007: {"notFound": True}})
        report = self.tmp / "run"
        with mock.patch.object(ks, "build_session", return_value=site), \
                mock.patch.object(ks, "random_delay"), mock.patch.object(ks.time, "sleep"):
            ks.scrape("quality assurance", 100, self.out, 0, 0, "NEW", None, None, report_dir=report)
        self.assertEqual(self.saved(), ["270006_quality-assurance-specialist-2.json"])
        data = json.loads((self.out / "270006_quality-assurance-specialist-2.json").read_text())
        self.assertEqual(data["pageProps"]["job"]["slug"], "qa-specialist-renamed")
        events = (report / "kalibrr_events.csv").read_text()
        self.assertIn("posting was not found", events)
        # the log lists the API URL that failed, not the job's page
        self.assertIn("https://www.kalibrr.com/_next/data/NEW/en/c/acme/jobs/270007/qa-tester.json"
                      "?code=acme&param=270007&param=qa-tester", events)
        self.assertNotIn("https://www.kalibrr.com/c/acme/jobs/270007/qa-tester,", events)

    def test_a_search_outage_is_waited_out(self):
        site = FakeKalibrr(search_fail=ks.MAX_RETRIES + 1)   # every retry fails, then the cooldown try works
        self.scrape(site, build_id="NEW")
        self.assertEqual(len(self.saved()), 2)

    def test_the_attached_job_answer_is_accepted(self):
        sample = {"pageProps": {"job": {"id": 270006, "slug": "quality-assurance-specialist-2"},
                                "isExpired": False}, "__N_SSG": True}
        session = mock.Mock()
        session.get.return_value = mock.Mock(status_code=200, json=mock.Mock(return_value=sample))
        got = ks.fetch_job_detail(session, "b0OjdSSX2x6M88sGm9htI", "multisys-technologies-corporation",
                                  270006, "quality-assurance-specialist-2")
        self.assertIs(got, sample)
        self.assertEqual(session.get.call_args.args[0],
                         "https://www.kalibrr.com/_next/data/b0OjdSSX2x6M88sGm9htI/en/c/"
                         "multisys-technologies-corporation/jobs/270006/quality-assurance-specialist-2.json"
                         "?code=multisys-technologies-corporation&param=270006"
                         "&param=quality-assurance-specialist-2")
