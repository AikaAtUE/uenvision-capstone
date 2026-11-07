#!/usr/bin/env python3
"""
Foundit Job Scraper
===================

Scrapes job postings from foundit.com.ph's public search API and saves each
individual job posting as its own JSON file (the search result pages
themselves are NOT saved). Same layout and options as kalibrr_scraper.py.

How it works
------------
1. GET  https://www.foundit.com.ph/home/api/searchResultsPage
            ?start={start}&limit={limit}&query={query}&queryDerived=true
            &countries=Philippines&variantName=DEFAULT
   -> returns {"data": [ {...}, ... ], "meta": {"paging": {"total": N, ...}}, ...}
2. For every job in the results, we pull:
       job_id = job["jobId"]          (the number at the end of the job page URL)
       jd_url = job["jdUrl"]          ("/job/it-manager-dempsey-...-69675292")
3. We fetch the full job post from
       https://www.foundit.com.ph/home/api/jobDetail?jobId={job_id}
   and save the JSON response as {job_id}_{slug}.json
   (a job ID foundit no longer has comes back as HTTP 200 with an empty {}).
4. start increases by `limit` each loop until start >= total (or --max-jobs is hit).
5. A random delay is inserted between *every* HTTP request.

Foundit returns at most 20 jobs per search page whatever `limit` asks for, so
--limit defaults to 20. Dates in the API (postedAt, createdAt, updatedAt,
closedAt) are Unix timestamps in milliseconds; compile_jobs_to_csv.py turns
createdAt into the posting's date.

Usage
-----
    python foundit_scraper.py --query "computer science" \
        --output-dir ./foundit_jobs --delay-min 1.5 --delay-max 4.0

    # Resume-safe: already-downloaded job files are skipped automatically.

    # Cap the number of jobs fetched (useful for testing):
    python foundit_scraper.py --query "data analyst" --max-jobs 20

    # More than one country (repeat the option):
    python foundit_scraper.py --query "computer science" --country Philippines --country Japan
"""

import argparse
import json
import logging
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

try:                                   # run as a script (the pipeline)
    from failed_saves import Recorder
except ImportError:                    # imported as myapp.pipeline.<scraper> (tests)
    from .failed_saves import Recorder

# --------------------------------------------------------------------------
# Config / constants
# --------------------------------------------------------------------------

SITE_URL = "https://www.foundit.com.ph"
SEARCH_URL = SITE_URL + "/home/api/searchResultsPage"
JOB_DETAIL_URL = SITE_URL + "/home/api/jobDetail"
PAGE_SIZE_CAP = 20          # foundit never returns more than this per search page
DEFAULT_COUNTRIES = ["Philippines"]

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

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0  # seconds; grows exponentially per retry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("foundit_scraper")

# Why the last get_json_with_retries() call returned None (for the failed saves log).
LAST_ERROR = ""


# --------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------

def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": SITE_URL + "/",
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
    global LAST_ERROR
    LAST_ERROR = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, headers=random_headers(), timeout=20)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 404:
                log.warning("404 Not Found: %s", url)
                LAST_ERROR = "HTTP 404 Not Found (the posting may have been taken down)"
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
            backoff = RETRY_BACKOFF_BASE * attempt
            time.sleep(backoff)

    log.error("Giving up on %s after %d attempts", url, MAX_RETRIES)
    return None


# --------------------------------------------------------------------------
# Core scraping logic
# --------------------------------------------------------------------------

def search_url(query: str, start: int, limit: int, countries: list[str]) -> str:
    params = [("start", start), ("limit", limit), ("query", query), ("queryDerived", "true")]
    params += [("countries", c) for c in countries]
    params.append(("variantName", "DEFAULT"))
    return f"{SEARCH_URL}?{urlencode(params)}"


def fetch_search_page(
    session: requests.Session, query: str, limit: int, start: int, countries: list[str]
) -> dict | None:
    log.info("Fetching search page: start=%d limit=%d query=%r", start, limit, query)
    return get_json_with_retries(session, search_url(query, start, limit, countries))


def fetch_job_detail(session: requests.Session, job_id) -> dict | None:
    """The full job post. None when the request failed or foundit has no job with that ID
    (it answers HTTP 200 with an empty {} for those)."""
    global LAST_ERROR
    data = get_json_with_retries(session, f"{JOB_DETAIL_URL}?{urlencode({'jobId': job_id})}")
    if data is None:
        return None
    if not isinstance(data, dict) or not data.get("jobId"):
        LAST_ERROR = "foundit returned no job for this ID (the posting may have been taken down)"
        log.warning("No job returned for jobId=%s", job_id)
        return None
    return data


def job_slug(job: dict) -> str:
    """'it-manager-dempsey-resource-management-philippines' from the jdUrl
    '/job/it-manager-dempsey-resource-management-philippines-69675292'."""
    jd_url = str(job.get("jdUrl") or "")
    slug = jd_url.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"-\d+$", "", slug)
    return slug or str(job.get("title") or "job")


def job_page_url(job: dict) -> str:
    jd_url = job.get("jdUrl")
    return f"{SITE_URL}{jd_url}" if jd_url else ""


def job_output_path(output_dir: Path, job_id, slug: str) -> Path:
    safe_slug = re.sub(r"[^A-Za-z0-9_-]+", "-", str(slug)).strip("-") or "job"
    return output_dir / f"{job_id}_{safe_slug}.json"


def scrape(
    query: str,
    limit: int,
    output_dir: Path,
    delay_min: float,
    delay_max: float,
    max_jobs: int | None,
    max_start: int | None,
    countries: list[str] | None = None,
    report_dir: Path | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    session = build_session()
    record = Recorder(report_dir, "foundit", query)
    countries = countries or DEFAULT_COUNTRIES
    limit = max(1, min(limit, PAGE_SIZE_CAP))

    start = 0
    total_count = None
    saved = 0
    skipped_existing = 0
    failed = 0

    while True:
        if max_start is not None and start >= max_start:
            log.info("Reached --max-start (%d). Stopping pagination.", max_start)
            break

        page = fetch_search_page(session, query, limit, start, countries)
        random_delay(delay_min, delay_max)

        if page is None:
            log.error("Search request failed at start=%d; stopping.", start)
            break

        if total_count is None:
            total_count = (((page.get("meta") or {}).get("paging") or {}).get("total")) or 0
            log.info("Total jobs reported by search API: %d", total_count)

        jobs = page.get("data") or []
        if not jobs:
            log.info("No more jobs returned at start=%d; stopping.", start)
            break

        for job in jobs:
            if max_jobs is not None and saved >= max_jobs:
                log.info("Reached --max-jobs (%d). Stopping.", max_jobs)
                _print_summary(saved, skipped_existing, failed)
                return

            job_id = job.get("jobId") or job.get("id")
            title = job.get("title") or ""
            company = (job.get("company") or {}).get("name") or job.get("companyName") or ""
            page_url = job_page_url(job)

            if not job_id:
                log.warning("Skipping job with no jobId: %s", title or "<unknown>")
                failed += 1
                record.failed("The search result has no job ID", "", title, company, page_url)
                continue

            slug = job_slug(job)
            out_path = job_output_path(output_dir, job_id, slug)
            if out_path.exists():
                log.info("Already have job %s (%s); skipping.", job_id, slug)
                skipped_existing += 1
                continue

            log.info("Fetching job detail: id=%s slug=%s", job_id, slug)
            detail = fetch_job_detail(session, job_id)
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

        start += len(jobs)
        if total_count and start >= total_count:
            log.info("Start (%d) has reached total count (%d); stopping.", start, total_count)
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
        description="Scrape foundit.com.ph job postings and save each as its own JSON file."
    )
    parser.add_argument(
        "--query", "-q", default="computer science",
        help="Search query text (default: 'computer science').",
    )
    parser.add_argument(
        "--limit", "-l", type=int, default=PAGE_SIZE_CAP,
        help=f"Results per search page (default and maximum: {PAGE_SIZE_CAP}).",
    )
    parser.add_argument(
        "--country", "-c", action="append", dest="countries", default=None,
        help="Country to search in; repeat for more than one (default: Philippines).",
    )
    parser.add_argument(
        "--output-dir", "-o", default="./foundit_jobs",
        help="Directory to save individual job JSON files into (default: ./foundit_jobs).",
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
        "--max-jobs", type=int, default=None,
        help="Stop after saving this many new jobs (default: no limit).",
    )
    parser.add_argument(
        "--max-start", type=int, default=None,
        help="Stop paginating once start reaches this value (default: no limit).",
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
        query=args.query,
        limit=args.limit,
        output_dir=Path(args.output_dir),
        delay_min=args.delay_min,
        delay_max=args.delay_max,
        max_jobs=args.max_jobs,
        max_start=args.max_start,
        countries=args.countries,
        report_dir=Path(args.report_dir) if args.report_dir else None,
    )


if __name__ == "__main__":
    main()
