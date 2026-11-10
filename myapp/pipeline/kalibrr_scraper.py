#!/usr/bin/env python3
"""
Kalibrr Job Scraper
====================

Scrapes job postings from Kalibrr's public search API and saves each
individual job posting as its own JSON file (the search result pages
themselves are NOT saved).

How it works
------------
1. GET  https://www.kalibrr.com/kjs/job_board/search?limit={limit}&offset={offset}&text={query}
   -> returns {"count": N, "jobs": [ {...}, ... ]}
2. For every job in the results, we pull:
       company_code = job["company"]["code"]
       job_id       = job["id"]
       slug         = job["slug"]
3. Those three values let us build the Next.js data URL for the full job page:
   https://www.kalibrr.com/_next/data/{build_id}/en/c/{company_code}/jobs/{job_id}/{slug}.json
       ?code={company_code}&param={job_id}&param={slug}
4. We fetch that URL and save the JSON response as {job_id}_{slug}.json
5. offset increases by `limit` each loop until offset >= count (or --max-jobs is hit).
6. A random delay is inserted between *every* HTTP request to avoid hammering
   the server / looking like a bot.

Only step 3 (the job details) needs a build id: the search API in step 1 doesn't.
The Next.js `build_id` in Kalibrr's data URLs changes whenever Kalibrr redeploys
their frontend, so it isn't hardcoded (see BuildId below):
  * it is looked up only when the first job detail is needed, from the HTML of
    that job's own page, then Kalibrr's homepage (any one of them is enough);
  * the last one found is kept in {output_dir}/.kalibrr_build_id, so the next run
    still works when Kalibrr's homepage is down;
  * when a job detail comes back 404/403, the build id is looked up again and the
    job is fetched once more if it changed (Kalibrr redeployed mid-run).
You can also pass --build-id to start from a known-good value.

Usage
-----
    python kalibrr_scraper.py --text "computer science" --limit 100 \
        --output-dir ./kalibrr_jobs --delay-min 1.5 --delay-max 4.0

    # Resume-safe: already-downloaded job files are skipped automatically.

    # Cap the number of jobs fetched (useful for testing):
    python kalibrr_scraper.py --text "data analyst" --max-jobs 20
"""

import argparse
import json
import logging
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests

try:                                   # run as a script (the pipeline)
    from failed_saves import Recorder
except ImportError:                    # imported as myapp.pipeline.<scraper> (tests)
    from .failed_saves import Recorder

# --------------------------------------------------------------------------
# Config / constants
# --------------------------------------------------------------------------

SEARCH_URL = "https://www.kalibrr.com/kjs/job_board/search"
HOME_URL = "https://www.kalibrr.com/"
# Pages tried, after the job's own page, when looking up the build id. Any Next.js
# page of Kalibrr's carries it, so one of them being down (the homepage often
# answers 500) doesn't stop the run.
BUILD_ID_PAGES = (HOME_URL, "https://www.kalibrr.com/home", "https://www.kalibrr.com/job-board/1")
BUILD_ID_FILE = ".kalibrr_build_id"      # kept in the output folder (git ignores it)
REFRESH_GAP = 300   # seconds: look the build id up again at most this often unless it changed
JOB_DETAIL_TEMPLATE = (
    "https://www.kalibrr.com/_next/data/{build_id}/en/c/{company_code}/"
    "jobs/{job_id}/{slug}.json?code={company_code}&param={job_id}&param={slug}"
)

# A small pool of realistic desktop User-Agents to rotate between requests.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:129.0) Gecko/20100101 Firefox/129.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Edg/128.0.0.0",
]

MAX_RETRIES = 5
RETRY_BACKOFF_BASE = 2.0  # seconds; doubles per retry (2, 4, 8, 16) so a short Kalibrr outage is waited out
SEARCH_COOLDOWN = 60      # seconds to wait before asking for a failed search page one last time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("kalibrr_scraper")

# Why the last get_json_with_retries() call returned None (for the failed saves log),
# and its HTTP status (None when there was no HTTP answer).
LAST_ERROR = ""
LAST_STATUS = None
JOB_PAGE_TEMPLATE = "https://www.kalibrr.com/c/{company_code}/jobs/{job_id}/{slug}"


# --------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------

def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.kalibrr.com/",
        }
    )
    return session


def random_headers() -> dict:
    """A fresh User-Agent per request to look a little less uniform."""
    return {"User-Agent": random.choice(USER_AGENTS)}


def random_delay(min_s: float, max_s: float) -> None:
    delay = random.uniform(min_s, max_s)
    log.debug("Sleeping %.2fs", delay)
    time.sleep(delay)


def get_json_with_retries(session: requests.Session, url: str) -> dict | None:
    """GET a URL and parse JSON, retrying with exponential backoff."""
    global LAST_ERROR, LAST_STATUS
    LAST_ERROR = ""
    LAST_STATUS = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, headers=random_headers(), timeout=20)
            LAST_STATUS = resp.status_code
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 404:
                log.warning("404 Not Found: %s", url)
                LAST_ERROR = "HTTP 404 Not Found (the posting may have been taken down)"
                return None
            if resp.status_code == 403:
                # Asking again doesn't change a 403; the caller may look the build id up again instead.
                log.warning("403 Forbidden: %s", url)
                LAST_ERROR = "HTTP 403 Forbidden (Kalibrr refused this posting)"
                return None
            LAST_ERROR = f"HTTP {resp.status_code} after {MAX_RETRIES} attempts"
            log.warning(
                "Attempt %d/%d: HTTP %d for %s",
                attempt, MAX_RETRIES, resp.status_code, url,
            )
        except requests.RequestException as exc:
            LAST_ERROR = f"Request error after {MAX_RETRIES} attempts: {type(exc).__name__}"
            log.warning(
                "Attempt %d/%d: request error for %s -> %s",
                attempt, MAX_RETRIES, url, exc,
            )
        except ValueError as exc:  # JSON decode error
            LAST_ERROR = f"The response wasn't valid JSON (after {MAX_RETRIES} attempts)"
            log.warning(
                "Attempt %d/%d: bad JSON from %s -> %s",
                attempt, MAX_RETRIES, url, exc,
            )

        if attempt < MAX_RETRIES:
            backoff = RETRY_BACKOFF_BASE * 2 ** (attempt - 1)
            time.sleep(backoff)

    log.error("Giving up on %s after %d attempts", url, MAX_RETRIES)
    return None


# --------------------------------------------------------------------------
# Next.js build_id discovery
# --------------------------------------------------------------------------

_BUILD_ID_RES = (
    ("__NEXT_DATA__", re.compile(r'"buildId"\s*:\s*"([^"]+)"')),
    ("static manifest path", re.compile(r"/_next/static/([A-Za-z0-9_-]+)/_buildManifest\.js")),
)


def discover_build_id(session: requests.Session, page_urls=None) -> str | None:
    """
    Kalibrr's job-detail data URLs are namespaced under a Next.js build id
    (e.g. /_next/data/{build_id}/...). This id changes on every Kalibrr
    deploy, so we read it live from a Kalibrr page's __NEXT_DATA__ /
    buildManifest reference instead of hardcoding it. `page_urls` are tried
    first (a job's own page), then BUILD_ID_PAGES; the first page that has it wins.
    """
    log.info("Discovering current Kalibrr Next.js build_id ...")
    tried = []
    for url in [*(page_urls or ()), *BUILD_ID_PAGES]:
        if not url or url in tried:
            continue
        tried.append(url)
        try:
            resp = session.get(url, headers={**random_headers(), "Accept": "text/html,*/*"}, timeout=20)
        except requests.RequestException as exc:
            log.warning("Couldn't open %s to look up the build_id: %s", url, exc)
            continue
        # A 404 page is a Next.js page too, so it still carries the build id.
        html = resp.text if resp.status_code in (200, 404) else ""
        if not html:
            log.warning("Couldn't open %s to look up the build_id: HTTP %s", url, resp.status_code)
            continue
        for where, pattern in _BUILD_ID_RES:
            match = pattern.search(html)
            if match:
                log.info("Discovered build_id (from %s of %s): %s", where, url, match.group(1))
                return match.group(1)
        log.warning("No build_id in the HTML of %s", url)

    log.error("Could not find Kalibrr's build_id on any of: %s", ", ".join(tried))
    return None


class BuildId:
    """
    The build id for job-detail URLs. Looked up only when a job detail is first needed,
    remembered in `cache_file` for the next run, and looked up again (at most once every
    REFRESH_GAP seconds) when Kalibrr seems to have redeployed.
    """

    def __init__(self, session, cache_file: Path | None = None, value: str | None = None):
        self.session = session
        self.cache_file = cache_file
        self.value = value or self._read_cache()
        if self.value and not value:
            log.info("Using the build_id saved by the last run: %s", self.value)
        self.checked_at = None          # time.monotonic() of the last lookup

    def _read_cache(self) -> str | None:
        try:
            return self.cache_file.read_text(encoding="utf-8").strip() or None if self.cache_file else None
        except OSError:
            return None

    def _save(self) -> None:
        if not self.cache_file:
            return
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(self.value, encoding="utf-8")
        except OSError as exc:
            log.warning("Couldn't save the build_id to %s: %s", self.cache_file, exc)

    def _can_check(self) -> bool:
        return self.checked_at is None or time.monotonic() - self.checked_at >= REFRESH_GAP

    def get(self, page_url: str | None = None) -> str | None:
        """The build id, looking it up if there isn't one yet (None if that failed)."""
        if not self.value and self._can_check():
            self.refresh(page_url, force=True)
        return self.value

    def refresh(self, page_url: str | None = None, force: bool = False) -> bool:
        """Look the build id up again; True when a new, different one was found."""
        if not force and not self._can_check():
            return False
        self.checked_at = time.monotonic()
        new = discover_build_id(self.session, [page_url] if page_url else None)
        if not new or new == self.value:
            return False
        if self.value:
            log.info("Kalibrr's build_id changed: %s -> %s", self.value, new)
        self.value = new
        self._save()
        return True


# --------------------------------------------------------------------------
# Core scraping logic
# --------------------------------------------------------------------------

def fetch_search_page(
    session: requests.Session, text: str, limit: int, offset: int
) -> dict | None:
    url = f"{SEARCH_URL}?limit={limit}&offset={offset}&text={quote(text)}"
    log.info("Fetching search page: offset=%d limit=%d text=%r", offset, limit, text)
    return get_json_with_retries(session, url)


REDIRECT_RE = re.compile(r"^/(?:en/)?c/([^/]+)/jobs/(\d+)/([^/?#]+)")


def fetch_job_detail(
    session: requests.Session, build_id: str, company_code: str, job_id, slug: str
) -> dict | None:
    """The job page data ({"pageProps": {"job": {...}, ...}}), or None (why: LAST_ERROR).

    When the slug or company code in the search result is out of date, Kalibrr answers
    {"pageProps": {"__N_REDIRECT": "/c/<code>/jobs/<id>/<slug>"}}; that redirect is followed
    once. Answers without a job in them are not returned, so they never get saved as job files.
    """
    global LAST_ERROR, LAST_STATUS
    for _ in range(2):
        url = JOB_DETAIL_TEMPLATE.format(
            build_id=quote(str(build_id)),
            company_code=quote(str(company_code)),
            job_id=job_id,
            slug=quote(str(slug)),
        )
        data = get_json_with_retries(session, url)
        if data is None:
            return None
        props = data.get("pageProps") if isinstance(data, dict) else None
        props = props if isinstance(props, dict) else {}
        if isinstance(props.get("job"), dict):
            return data
        match = REDIRECT_RE.match(str(props.get("__N_REDIRECT") or ""))
        if match and match.group(2) == str(job_id) and (match.group(1), match.group(3)) != (company_code, slug):
            company_code, slug = match.group(1), match.group(3)
            log.info("Job %s moved to /c/%s/jobs/%s/%s; following it.", job_id, company_code, job_id, slug)
            continue
        break
    LAST_STATUS = None
    LAST_ERROR = ("Kalibrr's answer had no job details (the posting may be closed or private)"
                  if not (isinstance(data, dict) and data.get("notFound")) else
                  "Kalibrr says the posting was not found")
    log.warning("No job details for job %s: %s", job_id, LAST_ERROR)
    return None


def job_output_path(output_dir: Path, job_id, slug: str) -> Path:
    safe_slug = re.sub(r"[^A-Za-z0-9_-]+", "-", str(slug)).strip("-")
    return output_dir / f"{job_id}_{safe_slug}.json"


def scrape(
    text: str,
    limit: int,
    output_dir: Path,
    delay_min: float,
    delay_max: float,
    build_id: str | None,
    max_jobs: int | None,
    max_offset: int | None,
    report_dir: Path | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    session = build_session()
    record = Recorder(report_dir, "kalibrr", text)

    # Only the job details need the build id, so it's looked up when the first one is needed.
    build = BuildId(session, output_dir / BUILD_ID_FILE, build_id)

    offset = 0
    total_count = None
    saved = 0
    skipped_existing = 0
    failed = 0

    while True:
        if max_offset is not None and offset >= max_offset:
            log.info("Reached --max-offset (%d). Stopping pagination.", max_offset)
            break

        page = fetch_search_page(session, text, limit, offset)
        random_delay(delay_min, delay_max)
        if page is None and LAST_STATUS != 404:
            # Kalibrr answers 500/502/503 for a minute or so now and then; wait it out once.
            log.warning("Search failed at offset=%d (%s); trying once more in %ds.",
                        offset, LAST_ERROR or "no response", SEARCH_COOLDOWN)
            time.sleep(SEARCH_COOLDOWN)
            page = fetch_search_page(session, text, limit, offset)
            random_delay(delay_min, delay_max)

        if page is None:
            log.error("Search request failed at offset=%d; stopping.", offset)
            break

        if total_count is None:
            total_count = page.get("count", 0)
            log.info("Total jobs reported by search API: %d", total_count)

        jobs = page.get("jobs", [])
        if not jobs:
            log.info("No more jobs returned at offset=%d; stopping.", offset)
            break

        for job in jobs:
            if max_jobs is not None and saved >= max_jobs:
                log.info("Reached --max-jobs (%d). Stopping.", max_jobs)
                _print_summary(saved, skipped_existing, failed)
                return

            job_id = job.get("id")
            slug = job.get("slug")
            company_code = (job.get("company") or {}).get("code")
            title = job.get("name") or ""
            company = (job.get("company") or {}).get("name") or job.get("company_name") or ""
            page_url = (JOB_PAGE_TEMPLATE.format(company_code=company_code, job_id=job_id, slug=slug)
                        if job_id and slug and company_code else "")

            if not job_id or not slug or not company_code:
                log.warning(
                    "Skipping job with missing id/slug/company_code: %s",
                    job.get("name", "<unknown>"),
                )
                failed += 1
                missing = [k for k, v in (("id", job_id), ("slug", slug), ("company code", company_code)) if not v]
                record.failed("The search result has no " + ", ".join(missing), job_id, title, company, page_url)
                continue

            out_path = job_output_path(output_dir, job_id, slug)
            if out_path.exists():
                log.info("Already have job %s (%s); skipping.", job_id, slug)
                skipped_existing += 1
                continue

            current = build.get(page_url)
            if not current:
                failed += 1
                record.failed("Couldn't fetch the job details: Kalibrr's build id couldn't be found "
                              "(its pages didn't load)", job_id, title, company, page_url)
                continue

            log.info("Fetching job detail: id=%s slug=%s company=%s", job_id, slug, company_code)
            detail = fetch_job_detail(session, current, company_code, job_id, slug)
            random_delay(delay_min, delay_max)
            if detail is None and LAST_STATUS in (403, 404) and build.refresh(page_url):
                # Kalibrr redeployed mid-run: the old build id's URLs stop working.
                detail = fetch_job_detail(session, build.value, company_code, job_id, slug)
                random_delay(delay_min, delay_max)

            if detail is None:
                failed += 1
                record.failed("Couldn't fetch the job details: " + (LAST_ERROR or "no response"),
                              job_id, title, company, page_url)
                continue

            try:
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(detail, f, ensure_ascii=False, indent=2)
            except (OSError, TypeError, ValueError) as exc:
                log.error("Couldn't write %s: %s", out_path, exc)
                failed += 1
                record.failed(f"Couldn't write the JSON file: {exc}", job_id, title, company, page_url)
                try:
                    out_path.unlink()       # a half-written file would be skipped as "already have" next time
                except OSError:
                    pass
                continue
            saved += 1
            record.saved(job_id, title, company, page_url)
            log.info("Saved -> %s", out_path)

        offset += limit
        if total_count is not None and offset >= total_count:
            log.info("Offset (%d) has reached total count (%d); stopping.", offset, total_count)
            break

    _print_summary(saved, skipped_existing, failed)


def _print_summary(saved: int, skipped_existing: int, failed: int) -> None:
    log.info(
        "Done. Saved=%d, Skipped(existing)=%d, Failed=%d",
        saved, skipped_existing, failed,
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape Kalibrr job postings and save each as its own JSON file."
    )
    parser.add_argument(
        "--text", "-t", default="computer science",
        help="Search query text (default: 'computer science').",
    )
    parser.add_argument(
        "--limit", "-l", type=int, default=100,
        help="Number of results per search page / API call (default: 100).",
    )
    parser.add_argument(
        "--output-dir", "-o", default="./kalibrr_jobs",
        help="Directory to save individual job JSON files into (default: ./kalibrr_jobs).",
    )
    parser.add_argument(
        "--delay-min", type=float, default=1.5,
        help="Minimum random delay (seconds) between requests (default: 1.5).",
    )
    parser.add_argument(
        "--delay-max", type=float, default=4.0,
        help="Maximum random delay (seconds) between requests (default: 4.0).",
    )
    parser.add_argument(
        "--build-id", default=None,
        help="Start from this Next.js build_id instead of looking it up (it's still "
             "looked up again if Kalibrr redeploys during the run).",
    )
    parser.add_argument(
        "--max-jobs", type=int, default=None,
        help="Stop after saving this many new jobs (default: no limit).",
    )
    parser.add_argument(
        "--max-offset", type=int, default=None,
        help="Stop paginating once offset reaches this value (default: no limit).",
    )
    parser.add_argument(
        "--report-dir", default=None,
        help="Folder for the failed saves log of this run (written by the Data Extraction page).",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging (shows per-request sleep timings, etc).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.verbose:
        log.setLevel(logging.DEBUG)

    if args.delay_min < 0 or args.delay_max < args.delay_min:
        log.error("Invalid delay range: --delay-min must be >= 0 and <= --delay-max.")
        sys.exit(1)

    scrape(
        text=args.text,
        limit=args.limit,
        output_dir=Path(args.output_dir),
        delay_min=args.delay_min,
        delay_max=args.delay_max,
        build_id=args.build_id,
        max_jobs=args.max_jobs,
        max_offset=args.max_offset,
        report_dir=Path(args.report_dir) if args.report_dir else None,
    )


if __name__ == "__main__":
    main()
