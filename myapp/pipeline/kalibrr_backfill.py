#!/usr/bin/env python3
"""
Kalibrr backfill: older (expired) tech job postings, by job ID
=============================================================

Kalibrr's search only returns open jobs, but an expired job's page data is still served
(full description, qualifications and dates, with pageProps.isExpired = true). So this
script walks a range of job IDs instead of searching, newest ID first:

1. GET https://www.kalibrr.com/_next/data/{build_id}/en/c/x/jobs/{job_id}/x.json
   -> {"pageProps": {"__N_REDIRECT": "/c/{company_code}/jobs/{job_id}/{slug}"}} for a job
      that exists (a 404 for an ID with no job). The slug is the job title.
2. Jobs whose title (slug) isn't a tech title are skipped here (see is_tech_slug()).
3. A tech job's real page data is fetched with kalibrr_scraper.fetch_job_detail() and saved
   as {job_id}_{slug}.json, the same file the search scraper writes, so the normal
   "Compile Kalibrr JSONs to CSV" step picks it up. Jobs created before --since are not saved.

Job IDs only roughly follow the creation date (Nov 2026 samples):
    ~236,400  -> early Jan 2024      ~250,000 -> Nov 2024
    ~260,000  -> Oct 2025            ~275,400 -> Nov 2026 (newest)

Resume-safe: IDs that already have a JSON file are skipped without a request, and the
lowest ID checked so far is kept in --progress-file, so a stopped run carries on from there.

Usage (on the server, from the project folder):
    nohup python3 myapp/pipeline/kalibrr_backfill.py --id-from 236400 --id-to 275500 \
        --output-dir data/jsons/kalibrr > kalibrr_backfill.log 2>&1 &
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

try:                                   # run as a script
    import kalibrr_scraper as ks
    from foundit_scraper import TECH_TITLE
except ImportError:                    # imported as myapp.pipeline.<module> (tests)
    from . import kalibrr_scraper as ks
    from .foundit_scraper import TECH_TITLE

log = logging.getLogger("kalibrr_backfill")
PROBE_TEMPLATE = ("https://www.kalibrr.com/_next/data/{build_id}/en/c/x/jobs/{job_id}/x.json"
                  "?code=x&param={job_id}&param=x")
REDIRECT_RE = re.compile(r"^/c/([^/]+)/jobs/(\d+)/([^/?#]+)")
MISSES_BEFORE_NEW_BUILD = 25   # this many IDs in a row with no job: check whether Kalibrr redeployed


def is_tech_slug(slug: str) -> bool:
    """A tech job title, judged from the URL slug ('senior-software-engineer')."""
    return bool(TECH_TITLE.search(str(slug).replace("-", " ")))


def probe(session, build_id: str, job_id: int):
    """-> (company_code, slug) for a job that exists, "missing" for an ID with no job,
    or None when the request failed."""
    url = PROBE_TEMPLATE.format(build_id=quote(build_id), job_id=job_id)
    try:
        resp = session.get(url, headers=ks.random_headers(), timeout=20)
    except Exception as exc:  # requests.RequestException and friends
        log.warning("Request failed for id=%s: %s", job_id, exc)
        return None
    if resp.status_code == 404:
        return "missing"
    if resp.status_code != 200:
        log.warning("HTTP %s for id=%s", resp.status_code, job_id)
        return None
    try:
        props = (resp.json() or {}).get("pageProps") or {}
    except ValueError:
        return None
    m = REDIRECT_RE.match(str(props.get("__N_REDIRECT") or ""))
    if m and int(m.group(2)) == job_id:
        return m.group(1), m.group(3)
    job = props.get("job")
    if isinstance(job, dict) and job.get("slug") and (job.get("company") or {}).get("code"):
        return job["company"]["code"], job["slug"]
    return "missing"


def existing_ids(output_dir: Path) -> set[int]:
    ids = set()
    for p in output_dir.glob("*.json"):
        head = p.name.split("_", 1)[0]
        if head.isdigit():
            ids.add(int(head))
    return ids


def created_before(detail: dict, since: str | None) -> bool:
    if not since:
        return False
    created = str((((detail or {}).get("pageProps") or {}).get("job") or {}).get("createdAt") or "")
    return bool(created) and created[:10] < since


def backfill(id_from: int, id_to: int, output_dir: Path, delay_min: float, delay_max: float,
             since: str | None = "2024-01-01", build_id: str | None = None,
             progress_file: Path | None = None, max_jobs: int | None = None,
             report_dir: Path | None = None) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    session = ks.build_session()
    record = ks.Recorder(report_dir, "kalibrr", f"ID backfill {id_from}-{id_to}")
    progress_file = progress_file or output_dir.parent / f".kalibrr_backfill_{id_from}_{id_to}.txt"

    start = id_to
    try:
        start = min(id_to, int(progress_file.read_text().strip()) - 1)
        log.info("Resuming below id %d (from %s).", start + 1, progress_file)
    except (OSError, ValueError):
        pass

    if not build_id:
        build_id = ks.discover_build_id(session)
        if not build_id:
            log.error("Aborting: no build_id available (pass --build-id to override).")
            sys.exit(1)
        ks.random_delay(delay_min, delay_max)

    have = existing_ids(output_dir)
    n = {"checked": 0, "saved": 0, "existing": 0, "not_tech": 0, "too_old": 0, "missing": 0, "failed": 0}
    misses = 0

    job_id = start + 1
    while job_id > id_from:
        job_id -= 1
        if max_jobs is not None and n["saved"] >= max_jobs:
            log.info("Reached --max-jobs (%d). Stopping.", max_jobs)
            break
        if job_id in have:
            n["existing"] += 1
            continue

        n["checked"] += 1
        found = probe(session, build_id, job_id)
        ks.random_delay(delay_min, delay_max)

        if found == "missing" or found is None:
            n["missing" if found == "missing" else "failed"] += 1
            misses += 1
            if misses >= MISSES_BEFORE_NEW_BUILD:
                new = ks.discover_build_id(session)
                ks.random_delay(delay_min, delay_max)
                if new and new != build_id:
                    log.info("Kalibrr redeployed (new build id); checking the last %d IDs again.", misses)
                    build_id = new
                    job_id += misses        # the loop steps back down through them
                misses = 0
            if job_id % 50 == 0:
                progress_file.write_text(str(job_id))
            continue
        misses = 0

        company_code, slug = found
        page_url = ks.JOB_PAGE_TEMPLATE.format(company_code=company_code, job_id=job_id, slug=slug)
        if not is_tech_slug(slug):
            n["not_tech"] += 1
            log.debug("Not a tech job; skipping %s (%s)", job_id, slug)
        else:
            detail = ks.fetch_job_detail(session, build_id, company_code, job_id, slug)
            ks.random_delay(delay_min, delay_max)
            if not (detail or {}).get("pageProps", {}).get("job"):
                n["failed"] += 1
                record.failed("Couldn't fetch the job details: " + (ks.LAST_ERROR or "no job in the response"),
                              job_id, slug, company_code, page_url)
            elif created_before(detail, since):
                n["too_old"] += 1
            else:
                out_path = ks.job_output_path(output_dir, job_id, slug)
                try:
                    out_path.write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
                except OSError as exc:
                    n["failed"] += 1
                    record.failed(f"Couldn't write the JSON file: {exc}", job_id, slug, company_code, page_url)
                    out_path.unlink(missing_ok=True)
                else:
                    n["saved"] += 1
                    job = detail["pageProps"]["job"]
                    record.saved(job_id, job.get("name") or slug, (job.get("company") or {}).get("name") or "",
                                 page_url)
                    log.info("Saved %s (%s, created %s)", out_path.name, job.get("name"),
                             str(job.get("createdAt") or "")[:10])

        if n["checked"] % 50 == 0:
            progress_file.write_text(str(job_id))
            log.info("At id %d: %s", job_id, n)

    progress_file.write_text(str(id_from))
    log.info("Done. %s", n)
    return n


def parse_args():
    p = argparse.ArgumentParser(description="Save older (expired) Kalibrr tech jobs by walking job IDs.")
    p.add_argument("--id-from", type=int, required=True, help="Lowest job ID to check.")
    p.add_argument("--id-to", type=int, required=True, help="Highest job ID to check (the walk starts here).")
    p.add_argument("--output-dir", "-o", default="./kalibrr_jobs", help="Where the job JSON files go.")
    p.add_argument("--since", default="2024-01-01",
                   help="Don't save jobs created before this date (YYYY-MM-DD; '' = no limit).")
    p.add_argument("--delay-min", type=float, default=1.5)
    p.add_argument("--delay-max", type=float, default=4.0)
    p.add_argument("--build-id", default=None)
    p.add_argument("--max-jobs", type=int, default=None, help="Stop after saving this many jobs.")
    p.add_argument("--progress-file", default=None)
    p.add_argument("--report-dir", default=None)
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%H:%M:%S")
    if args.id_from > args.id_to or args.delay_min < 0 or args.delay_max < args.delay_min:
        log.error("Check --id-from/--id-to and the delays.")
        sys.exit(1)
    if args.since:
        datetime.strptime(args.since, "%Y-%m-%d")
    backfill(args.id_from, args.id_to, Path(args.output_dir), args.delay_min, args.delay_max,
             since=args.since or None, build_id=args.build_id,
             progress_file=Path(args.progress_file) if args.progress_file else None,
             max_jobs=args.max_jobs, report_dir=Path(args.report_dir) if args.report_dir else None)


if __name__ == "__main__":
    main()
