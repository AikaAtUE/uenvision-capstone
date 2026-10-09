#!/usr/bin/env python3
"""
Trabajo.org (Philippines) Job Scraper
=====================================

Scrapes job postings from https://ph.trabajo.org and saves every individual
job posting as its own JSON file (search-result pages are NOT saved).

How it works
------------
1. Build the search URL:
       page 1  -> https://ph.trabajo.org/jobs-{keyword+with+plus}
       page >1 -> https://ph.trabajo.org/jobs-{keyword+with+plus}?page={n}
2. Parse the listing: every <li class="nf-job"> card gives a job URL such as
       https://ph.trabajo.org/job-2273-d1566cf245aa42e256479c06ebfcc273
   plus a few listing-only fields (snippet, "2 days ago", data-id ...).
3. Fetch every job URL and extract, from the JobPosting JSON-LD block AND the
   visible job card: title, company, location, employment type, salary,
   posted / expiry dates, full description (text + HTML), category, etc.
   "Related jobs" embedded in the page are ignored on purpose.
4. Save each job as  <output-dir>/job-<source>-<hash>.json
5. Pagination ends ONLY when there is no "Next" link any more. The site shows
   page numbers up to 50, but we never rely on that number - we follow "Next"
   for as long as it exists.

Safety / politeness measures (adapted from kalibrr_scraper.py + extras)
-----------------------------------------------------------------------
 From kalibrr_scraper.py:
   * persistent requests.Session with realistic default headers
   * rotating User-Agent per request
   * random delay between EVERY request
   * retries with growing back-off
   * 404 handled without retrying; bad responses never crash the run
   * resume-safe: job files that already exist are skipped
   * --max-jobs / --max-pages caps and delay-range validation
 Added for this script:
   * robots.txt is fetched and respected
   * domain allow-list (only https://ph.trabajo.org); redirects that leave it
     are rejected; "Next" links must stay on the same search path
   * strict regex validation of job URLs before they are requested
   * honours HTTP 429/503 "Retry-After" (capped)
   * circuit breaker: abort after N consecutive failed requests
   * response size cap + Content-Type check (HTML only)
   * atomic file writes (tmp file + rename) so no half-written JSON
   * sanitized filenames derived from the validated URL (no path traversal)
   * loop guards: visited-page set and "page only repeats known jobs" stop
   * login / redirect / tracking links are never followed

Usage
-----
    python trabajo_scraper.py --keyword "computer science" -o ./trabajo_jobs
    python trabajo_scraper.py -k "data analyst" --max-jobs 20 -v

    # Offline parser checks (no network):
    python trabajo_scraper.py --test-listing output.html
    python trabajo_scraper.py --test-detail  job_posting_sample.html
"""

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

# --------------------------------------------------------------------------
# Config / constants
# --------------------------------------------------------------------------

BASE_HOST = "ph.trabajo.org"
BASE_URL = f"https://{BASE_HOST}"
ALLOWED_HOSTS = {BASE_HOST}

# Only URLs shaped like /job-<digits>-<alnum hash> are ever requested as jobs.
JOB_PATH_RE = re.compile(r"^/job-(\d+)-([A-Za-z0-9]{8,64})$")

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
RETRY_BACKOFF_BASE = 2.0         # seconds; multiplied by attempt number
MAX_RETRY_AFTER = 120            # never sleep longer than this for Retry-After
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
REQUEST_TIMEOUT = (10, 25)       # (connect, read) seconds
DEFAULT_MAX_CONSECUTIVE_FAILURES = 5

JOB_TYPE_WORDS = {
    "full-time", "part-time", "contract", "internship", "temporary",
    "freelance", "permanent", "casual", "volunteer",
}
WORK_MODE_WORDS = {"remote", "hybrid", "on-site", "onsite", "work from home"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("trabajo_scraper")


class AbortScrape(Exception):
    """Raised by the circuit breaker to stop the whole run safely."""


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def clean(text: str | None) -> str:
    """Collapse all whitespace runs into single spaces."""
    return re.sub(r"\s+", " ", text or "").strip()


def is_allowed_url(url: str) -> bool:
    p = urlparse(url)
    return p.scheme == "https" and p.hostname in ALLOWED_HOSTS


def is_job_url(url: str) -> bool:
    return is_allowed_url(url) and bool(JOB_PATH_RE.match(urlparse(url).path))


def build_listing_url(keyword: str, page: int) -> str:
    # "computer science" -> "computer+science"
    job_name = quote_plus(keyword.strip())
    url = f"{BASE_URL}/jobs-{job_name}"
    if page > 1:
        url += f"?page={page}"
    return url


def job_output_path(output_dir: Path, job_url: str) -> Path:
    """/job-2273-abc123 -> <output_dir>/job-2273-abc123.json (validated)."""
    path = urlparse(job_url).path
    m = JOB_PATH_RE.match(path)
    if not m:
        raise ValueError(f"Not a valid job URL: {job_url}")
    return output_dir / f"job-{m.group(1)}-{m.group(2)}.json"


def atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# HTTP layer
# --------------------------------------------------------------------------

def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"{BASE_URL}/",
        }
    )
    return session


def random_headers() -> dict:
    return {"User-Agent": random.choice(USER_AGENTS)}


def random_delay(min_s: float, max_s: float) -> None:
    delay = random.uniform(min_s, max_s)
    log.debug("Sleeping %.2fs", delay)
    time.sleep(delay)


class Fetcher:
    """HTTP GET wrapper with retries, size cap, host checks and a circuit breaker."""

    def __init__(self, session: requests.Session, max_consecutive_failures: int):
        self.session = session
        self.max_failures = max_consecutive_failures
        self.consecutive_failures = 0

    def _record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.max_failures:
            raise AbortScrape(
                f"{self.consecutive_failures} consecutive failed requests - "
                "stopping to avoid hammering the server (possible block)."
            )

    def get_html(self, url: str) -> str | None:
        if not is_allowed_url(url):
            log.error("Refusing to fetch non-allow-listed URL: %s", url)
            return None

        for attempt in range(1, MAX_RETRIES + 1):
            wait = RETRY_BACKOFF_BASE * attempt
            try:
                with self.session.get(
                    url, headers=random_headers(), timeout=REQUEST_TIMEOUT,
                    stream=True, allow_redirects=True,
                ) as resp:
                    # A redirect (e.g. to a login/captcha/other domain) must stay on-site.
                    if not is_allowed_url(resp.url):
                        log.error("Redirected off-site (%s -> %s); rejecting.", url, resp.url)
                        self._record_failure()
                        return None

                    if resp.status_code == 200:
                        ctype = resp.headers.get("Content-Type", "")
                        if "html" not in ctype.lower():
                            log.warning("Unexpected Content-Type %r for %s", ctype, url)
                            self._record_failure()
                            return None
                        body = self._read_capped(resp)
                        if body is None:
                            self._record_failure()
                            return None
                        self.consecutive_failures = 0
                        return body

                    if resp.status_code == 404:
                        log.warning("404 Not Found: %s", url)
                        return None  # not a "block" signal; don't count it

                    if resp.status_code in (429, 503):
                        retry_after = resp.headers.get("Retry-After", "")
                        if retry_after.isdigit():
                            wait = min(int(retry_after), MAX_RETRY_AFTER)
                        else:
                            wait = min(wait * 5, MAX_RETRY_AFTER)
                        log.warning("HTTP %d (rate-limited?) for %s; waiting %ds",
                                    resp.status_code, url, wait)
                    else:
                        log.warning("Attempt %d/%d: HTTP %d for %s",
                                    attempt, MAX_RETRIES, resp.status_code, url)
            except requests.RequestException as exc:
                log.warning("Attempt %d/%d: request error for %s -> %s",
                            attempt, MAX_RETRIES, url, exc)

            if attempt < MAX_RETRIES:
                time.sleep(wait)

        log.error("Giving up on %s after %d attempts", url, MAX_RETRIES)
        self._record_failure()
        return None

    @staticmethod
    def _read_capped(resp: requests.Response) -> str | None:
        chunks, size = [], 0
        for chunk in resp.iter_content(chunk_size=65536):
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                log.error("Response exceeded %d bytes; discarding.", MAX_RESPONSE_BYTES)
                return None
            chunks.append(chunk)
        raw = b"".join(chunks)
        m = re.search(r"charset=([\w-]+)", resp.headers.get("Content-Type", ""), re.I)
        return raw.decode(m.group(1) if m else "utf-8", errors="replace")


def load_robots(session: requests.Session) -> RobotFileParser | None:
    """Fetch and parse robots.txt. Returns None if it can't be retrieved."""
    url = f"{BASE_URL}/robots.txt"
    try:
        resp = session.get(url, headers=random_headers(), timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200 and is_allowed_url(resp.url):
            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
            log.info("robots.txt loaded.")
            return rp
        log.warning("robots.txt returned HTTP %d; continuing without it.", resp.status_code)
    except requests.RequestException as exc:
        log.warning("Could not fetch robots.txt (%s); continuing without it.", exc)
    return None


def robots_allows(rp: RobotFileParser | None, url: str) -> bool:
    return True if rp is None else rp.can_fetch("*", url)


# --------------------------------------------------------------------------
# Parsing: listing page
# --------------------------------------------------------------------------

def parse_listing_page(html: str, page_url: str) -> dict:
    """
    Returns {"jobs": [...], "next_url": str | None}.
    Each job dict holds listing-only fields; the job URL is the key to fetch details.
    """
    soup = BeautifulSoup(html, "lxml")
    jobs, seen = [], set()

    for li in soup.select("li.nf-job"):
        url = li.get("data-url") or ""
        if not url:
            a = li.select_one("h2 a[href], h3 a[href]")
            url = a["href"] if a else ""
        url = urljoin(page_url, url)
        if not is_job_url(url) or url in seen:
            continue
        seen.add(url)

        a = li.select_one("h2 a, h3 a")
        posted = li.select_one("p.text-muted small")
        snippet = li.select_one(".nf-job-list-desc > p")

        info = {}
        for span in li.select(".nf-job-list-info > span"):
            icon = span.find("i")
            icon_cls = " ".join(icon.get("class", [])) if icon else ""
            value = clean(span.get_text(" "))
            if "map-marker" in icon_cls:
                info["location"] = value
            elif "briefcase" in icon_cls:
                info["company"] = value
            elif "laptop-phone" in icon_cls:
                info["work_mode"] = value
            elif "clock" in icon_cls:
                info["job_type"] = value
            elif "diamond" in icon_cls:
                info["salary_raw"] = value

        jobs.append(
            {
                "url": url,
                "data_id": li.get("data-id"),
                "source_id": li.get("data-fuente"),
                "title": clean(a.get_text()) if a else None,
                "posted_relative": clean(posted.get_text()) if posted else None,
                "snippet": clean(snippet.get_text()) if snippet else None,
                **info,
            }
        )

    return {"jobs": jobs, "next_url": find_next_url(soup, page_url)}


def find_next_url(soup: BeautifulSoup, page_url: str) -> str | None:
    """Return the validated URL behind the 'Next' pagination link, or None."""
    for a in soup.select("ul.pagination li.page-item a[href]"):
        if clean(a.get_text()).lower() != "next":
            continue
        nxt = urljoin(page_url, a["href"])
        # Must stay on-site AND on the same search path (/jobs-<keyword>).
        if is_allowed_url(nxt) and urlparse(nxt).path == urlparse(page_url).path:
            return nxt
        log.warning("Ignoring suspicious 'Next' link: %s", nxt)
    return None


# --------------------------------------------------------------------------
# Parsing: job detail page
# --------------------------------------------------------------------------

def parse_salary(raw: str | None) -> dict | None:
    if not raw:
        return None
    nums = []
    for n in re.findall(r"\d[\d,]*(?:\.\d+)?", raw):
        v = float(n.replace(",", ""))
        nums.append(int(v) if v.is_integer() else v)
    currency = "PHP" if "₱" in raw or "PHP" in raw.upper() else ("USD" if "$" in raw else None)
    period = None
    m = re.search(r"/\s*(hour|day|week|month|year)|per\s+(hour|day|week|month|year)", raw, re.I)
    if m:
        period = (m.group(1) or m.group(2)).lower()
    return {
        "raw": raw,
        "currency": currency,
        "min": nums[0] if nums else None,
        "max": nums[1] if len(nums) > 1 else (nums[0] if nums else None),
        "period": period,   # None when the site doesn't state one
    }


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "lxml")
    for li in soup.find_all("li"):
        li.insert_before("\n- ")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for blk in soup.find_all(["p", "h1", "h2", "h3", "h4", "ul", "ol", "div"]):
        blk.append("\n")
    text = soup.get_text()
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{2,}(?=- )", "\n", text)   # no blank line before bullets
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _jsonld_blocks(soup: BeautifulSoup) -> list:
    out = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (ValueError, TypeError):
            continue
        out.extend(data if isinstance(data, list) else [data])
    return out


def parse_job_detail(html: str, job_url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    blocks = _jsonld_blocks(soup)
    posting = next((b for b in blocks if b.get("@type") == "JobPosting"), {})
    crumbs_ld = next((b for b in blocks if b.get("@type") == "BreadcrumbList"), {})

    # Only look inside the MAIN card - the page also embeds "related jobs".
    card = soup.select_one(".card-tr.nf-job") or soup
    h1 = card.select_one("h1")
    date_el = card.select_one(".job-date")
    chips = [clean(c.get_text(" ")) for c in card.select(".job-chip")]
    salary_chip = card.select_one(".job-chip-salary")

    # ---- classify chips: location, company, work mode, job type, salary
    chip_location = chips[0] if chips else None
    chip_company = chips[1] if len(chips) > 1 else None
    chip_type = chip_mode = None
    for c in chips[2:]:
        low = c.lower()
        if low in JOB_TYPE_WORDS and not chip_type:
            chip_type = c
        elif low in WORK_MODE_WORDS and not chip_mode:
            chip_mode = c
    salary_raw = clean(salary_chip.get_text(" ")) if salary_chip else None

    # ---- JSON-LD pieces
    org = posting.get("hiringOrganization") or {}
    addr = (posting.get("jobLocation") or {}).get("address") or {}
    if isinstance(posting.get("jobLocation"), list):  # tolerate list form
        addr = (posting["jobLocation"][0] or {}).get("address") or {}
    desc_html = posting.get("description") or ""
    if not desc_html:
        d = card.select_one(".job-desc-formatted")
        desc_html = d.decode_contents() if d else ""

    salary = parse_salary(salary_raw)
    base = posting.get("baseSalary")
    if salary is None and isinstance(base, dict):
        val = base.get("value") or {}
        salary = {
            "raw": None, "currency": base.get("currency"),
            "min": val.get("minValue", val.get("value")),
            "max": val.get("maxValue", val.get("value")),
            "period": (val.get("unitText") or "").lower() or None,
        }

    # ---- breadcrumbs / category
    breadcrumbs = [
        {"name": i.get("name"), "url": i.get("item")}
        for i in crumbs_ld.get("itemListElement", [])
    ]
    category = next(
        ({"name": b["name"], "url": b["url"]} for b in breadcrumbs
         if b.get("url") and "/browsejobs/categories" in b["url"]),
        None,
    )

    canonical = soup.find("link", rel="canonical")
    m = JOB_PATH_RE.match(urlparse(job_url).path)

    return {
        "job_id": f"{m.group(1)}-{m.group(2)}" if m else None,
        "source_id": m.group(1) if m else None,
        "identifier": (posting.get("identifier") or {}).get("value"),
        "url": job_url,
        "canonical_url": canonical["href"] if canonical and canonical.get("href") else job_url,
        "title": posting.get("title") or (clean(h1.get_text()) if h1 else None),
        "company": {
            "name": org.get("name") or chip_company,
            "logo_url": org.get("logo"),
        },
        "location": {
            "raw": chip_location,
            "locality": addr.get("addressLocality"),
            "region": addr.get("addressRegion"),
            "country": addr.get("addressCountry"),
        },
        "employment_type": {
            "raw": chip_type,
            "schema": posting.get("employmentType"),
        },
        "work_mode": chip_mode,
        "salary": salary,
        "date_posted": posting.get("datePosted"),
        "valid_through": posting.get("validThrough"),
        "posted_relative": clean(date_el.get_text()) if date_el else None,
        "direct_apply": posting.get("directApply"),
        "description_text": html_to_text(desc_html),
        "description_html": desc_html,
        "category": category,
        "breadcrumbs": breadcrumbs,
        "chips_raw": chips,
    }


# --------------------------------------------------------------------------
# Core scraping logic
# --------------------------------------------------------------------------

def scrape(
    keyword: str,
    output_dir: Path,
    delay_min: float,
    delay_max: float,
    max_jobs: int | None,
    max_pages: int | None,
    start_page: int,
    max_failures: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    session = build_session()
    fetcher = Fetcher(session, max_failures)

    rp = load_robots(session)
    random_delay(delay_min, delay_max)

    page_num = start_page
    page_url = build_listing_url(keyword, page_num)
    visited_pages: set[str] = set()
    seen_job_urls: set[str] = set()
    saved = skipped = failed = pages_done = 0

    try:
        while page_url:
            if max_pages is not None and pages_done >= max_pages:
                log.info("Reached --max-pages (%d). Stopping.", max_pages)
                break
            if page_url in visited_pages:
                log.warning("Page already visited (%s); loop guard stopping.", page_url)
                break
            visited_pages.add(page_url)

            if not robots_allows(rp, page_url):
                log.error("robots.txt disallows %s; stopping.", page_url)
                break

            log.info("Fetching listing page %d: %s", page_num, page_url)
            html = fetcher.get_html(page_url)
            random_delay(delay_min, delay_max)
            if html is None:
                log.error("Listing request failed on page %d; stopping.", page_num)
                break
            pages_done += 1

            listing = parse_listing_page(html, page_url)
            jobs = listing["jobs"]
            if not jobs:
                log.info("No jobs found on page %d; stopping.", page_num)
                break

            fresh = [j for j in jobs if j["url"] not in seen_job_urls]
            if not fresh:
                log.warning("Page %d only repeats jobs already seen; stopping.", page_num)
                break
            log.info("Page %d: %d jobs (%d new this run).", page_num, len(jobs), len(fresh))

            for job in fresh:
                seen_job_urls.add(job["url"])
                if max_jobs is not None and saved >= max_jobs:
                    log.info("Reached --max-jobs (%d). Stopping.", max_jobs)
                    _print_summary(saved, skipped, failed)
                    return

                out_path = job_output_path(output_dir, job["url"])
                if out_path.exists():
                    log.info("Already have %s; skipping.", out_path.name)
                    skipped += 1
                    continue

                if not robots_allows(rp, job["url"]):
                    log.warning("robots.txt disallows %s; skipping.", job["url"])
                    failed += 1
                    continue

                log.info("Fetching job: %s", job["url"])
                detail_html = fetcher.get_html(job["url"])
                random_delay(delay_min, delay_max)
                if detail_html is None:
                    failed += 1
                    continue

                try:
                    record = parse_job_detail(detail_html, job["url"])
                except Exception as exc:  # parsing bug must not kill the run
                    log.error("Parse error for %s: %s", job["url"], exc)
                    failed += 1
                    continue

                record["listing"] = {
                    "page_number": page_num,
                    "data_id": job.get("data_id"),
                    "posted_relative": job.get("posted_relative"),
                    "snippet": job.get("snippet"),
                    "salary_raw": job.get("salary_raw"),
                }
                record["search_keyword"] = keyword
                record["scraped_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

                atomic_write_json(out_path, record)
                saved += 1
                log.info("Saved -> %s", out_path)

            # Pagination ends ONLY when there is no "Next" button.
            page_url = listing["next_url"]
            if page_url is None:
                log.info("No 'Next' button on page %d - reached the end.", page_num)
            page_num += 1

    except AbortScrape as exc:
        log.error("ABORTED: %s", exc)
    except KeyboardInterrupt:
        log.warning("Interrupted by user; progress is saved (re-run to resume).")

    _print_summary(saved, skipped, failed)


def _print_summary(saved: int, skipped: int, failed: int) -> None:
    log.info("Done. Saved=%d, Skipped(existing)=%d, Failed=%d", saved, skipped, failed)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Scrape ph.trabajo.org job postings; one JSON file per job."
    )
    p.add_argument("--keyword", "-k", default="computer science",
                   help="Search keyword(s) (default: 'computer science').")
    p.add_argument("--output-dir", "-o", default="./trabajo_jobs",
                   help="Directory for per-job JSON files (default: ./trabajo_jobs).")
    p.add_argument("--delay-min", type=float, default=0.5,
                   help="Minimum random delay between requests, seconds (default: 0.5).")
    p.add_argument("--delay-max", type=float, default=1.5,
                   help="Maximum random delay between requests, seconds (default: 1.5).")
    p.add_argument("--max-jobs", type=int, default=None,
                   help="Stop after saving this many NEW jobs (default: no limit).")
    p.add_argument("--max-pages", type=int, default=None,
                   help="Stop after this many listing pages (default: until no 'Next').")
    p.add_argument("--start-page", type=int, default=1,
                   help="Listing page to start from (default: 1).")
    p.add_argument("--max-failures", type=int, default=DEFAULT_MAX_CONSECUTIVE_FAILURES,
                   help="Abort after this many consecutive failed requests (default: 5).")
    p.add_argument("--verbose", "-v", action="store_true", help="Debug logging.")
    p.add_argument("--test-listing", metavar="HTML_FILE",
                   help="Parse a saved listing page offline and print the result.")
    p.add_argument("--test-detail", metavar="HTML_FILE",
                   help="Parse a saved job page offline and print the result.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.verbose:
        log.setLevel(logging.DEBUG)

    # ---- offline parser checks (no network)
    if args.test_listing:
        html = Path(args.test_listing).read_text(encoding="utf-8")
        url = build_listing_url(args.keyword, 1)
        print(json.dumps(parse_listing_page(html, url), ensure_ascii=False, indent=2))
        return
    if args.test_detail:
        html = Path(args.test_detail).read_text(encoding="utf-8")
        canon = BeautifulSoup(html, "lxml").find("link", rel="canonical")
        url = canon["href"] if canon else f"{BASE_URL}/job-0-00000000"
        print(json.dumps(parse_job_detail(html, url), ensure_ascii=False, indent=2))
        return

    # ---- validation
    if args.delay_min < 0 or args.delay_max < args.delay_min:
        log.error("Invalid delay range: need 0 <= --delay-min <= --delay-max.")
        sys.exit(1)
    if not args.keyword.strip():
        log.error("--keyword must not be empty.")
        sys.exit(1)
    if args.start_page < 1 or args.max_failures < 1:
        log.error("--start-page and --max-failures must be >= 1.")
        sys.exit(1)

    scrape(
        keyword=args.keyword,
        output_dir=Path(args.output_dir),
        delay_min=args.delay_min,
        delay_max=args.delay_max,
        max_jobs=args.max_jobs,
        max_pages=args.max_pages,
        start_page=args.start_page,
        max_failures=args.max_failures,
    )


if __name__ == "__main__":
    main()
