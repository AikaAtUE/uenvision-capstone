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

The Next.js `build_id` embedded in Kalibrr's data URLs changes whenever
Kalibrr redeploys their frontend. Rather than hardcoding it, this script
scrapes the current build_id from the Kalibrr homepage automatically. You
can also pass --build-id to skip that step / pin a known-good value.

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

# --------------------------------------------------------------------------
# Config / constants
# --------------------------------------------------------------------------

SEARCH_URL = "https://www.kalibrr.com/kjs/job_board/search"
HOME_URL = "https://www.kalibrr.com/"
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

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0  # seconds; grows exponentially per retry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("kalibrr_scraper")


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
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, headers=random_headers(), timeout=20)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 404:
                log.warning("404 Not Found: %s", url)
                return None
            log.warning(
                "Attempt %d/%d: HTTP %d for %s",
                attempt, MAX_RETRIES, resp.status_code, url,
            )
        except requests.RequestException as exc:
            log.warning(
                "Attempt %d/%d: request error for %s -> %s",
                attempt, MAX_RETRIES, url, exc,
            )
        except ValueError as exc:  # JSON decode error
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
# Next.js build_id discovery
# --------------------------------------------------------------------------

def discover_build_id(session: requests.Session) -> str | None:
    """
    Kalibrr's job-detail data URLs are namespaced under a Next.js build id
    (e.g. /_next/data/{build_id}/...). This id changes on every Kalibrr
    deploy, so we scrape it live from the homepage's __NEXT_DATA__ /
    buildManifest reference instead of hardcoding it.
    """
    log.info("Discovering current Kalibrr Next.js build_id ...")
    try:
        resp = session.get(HOME_URL, headers=random_headers(), timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.error("Could not fetch homepage to discover build_id: %s", exc)
        return None

    html = resp.text

    # Most reliable: the __NEXT_DATA__ script tag contains {"buildId":"..."}
    match = re.search(r'"buildId"\s*:\s*"([^"]+)"', html)
    if match:
        build_id = match.group(1)
        log.info("Discovered build_id (from __NEXT_DATA__): %s", build_id)
        return build_id

    # Fallback: look for /_next/static/{build_id}/_buildManifest.js references
    match = re.search(r"/_next/static/([A-Za-z0-9_-]+)/_buildManifest\.js", html)
    if match:
        build_id = match.group(1)
        log.info("Discovered build_id (from static manifest path): %s", build_id)
        return build_id

    log.error("Could not locate build_id in homepage HTML.")
    return None


# --------------------------------------------------------------------------
# Core scraping logic
# --------------------------------------------------------------------------

def fetch_search_page(
    session: requests.Session, text: str, limit: int, offset: int
) -> dict | None:
    url = f"{SEARCH_URL}?limit={limit}&offset={offset}&text={quote(text)}"
    log.info("Fetching search page: offset=%d limit=%d text=%r", offset, limit, text)
    return get_json_with_retries(session, url)


def fetch_job_detail(
    session: requests.Session, build_id: str, company_code: str, job_id, slug: str
) -> dict | None:
    url = JOB_DETAIL_TEMPLATE.format(
        build_id=build_id,
        company_code=quote(str(company_code)),
        job_id=job_id,
        slug=quote(str(slug)),
    )
    return get_json_with_retries(session, url)


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
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    session = build_session()

    if not build_id:
        build_id = discover_build_id(session)
        if not build_id:
            log.error("Aborting: no build_id available (pass --build-id to override).")
            sys.exit(1)
        random_delay(delay_min, delay_max)

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

            if not job_id or not slug or not company_code:
                log.warning(
                    "Skipping job with missing id/slug/company_code: %s",
                    job.get("name", "<unknown>"),
                )
                failed += 1
                continue

            out_path = job_output_path(output_dir, job_id, slug)
            if out_path.exists():
                log.info("Already have job %s (%s); skipping.", job_id, slug)
                skipped_existing += 1
                continue

            log.info("Fetching job detail: id=%s slug=%s company=%s", job_id, slug, company_code)
            detail = fetch_job_detail(session, build_id, company_code, job_id, slug)
            random_delay(delay_min, delay_max)

            if detail is None:
                failed += 1
                continue

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(detail, f, ensure_ascii=False, indent=2)
            saved += 1
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
        help="Override the Next.js build_id instead of auto-discovering it.",
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
    )


if __name__ == "__main__":
    main()
