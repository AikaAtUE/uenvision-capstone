#!/usr/bin/env python3
"""
Job JSON -> CSV Compiler  (Kalibrr + Trabajo)
=============================================

Reads every individual job-posting JSON file saved by one of the scrapers
and compiles them into a single CSV file, using that source's column schema.

    --source kalibrr   JSON files from kalibrr_scraper.py   (default)
    --source trabajo   JSON files from trabajo_scraper.py

Usage
-----
    # Kalibrr
    python compile_jobs_to_csv.py --source kalibrr \
        --input-dir ./kalibrr_jobs --output-csv kalibrr_jobs.csv

    # Trabajo
    python compile_jobs_to_csv.py --source trabajo \
        --input-dir ./trabajo_jobs --output-csv trabajo_jobs.csv

    # If --input-dir / --output-csv are omitted, each source uses its own
    # defaults (./kalibrr_jobs -> ./kalibrr_jobs.csv, ./trabajo_jobs -> ./trabajo_jobs.csv).

    # Re-run any time after scraping more jobs -- it always rebuilds the
    # CSV from scratch from whatever *.json files currently exist.

Note: the CSV is written as UTF-8 with a BOM ("utf-8-sig") so Excel displays
characters such as the peso sign (₱) correctly. pandas reads it fine as well.
"""

import argparse
import csv
import html
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("compile_jobs_to_csv")

# --------------------------------------------------------------------------
# Final CSV column schemas (order matters -- this is the header row)
# --------------------------------------------------------------------------

KALIBRR_FIELDNAMES = [
    "job_id",
    "job_title",
    "slug",
    "job_url",
    "company_name",
    "company_code",
    "company_industry",
    "company_url",
    "company_verified",
    "function",
    "tenure",
    "number_of_openings",
    "work_experience_code",
    "months_work_experience",
    "education_level_code",
    "open_to_fresh_grads",
    "is_hybrid",
    "is_work_from_home",
    "city",
    "region",
    "country",
    "formatted_address",
    "latitude",
    "longitude",
    "salary_shown",
    "base_salary",
    "maximum_salary",
    "salary_currency",
    "salary_interval",
    "description",
    "qualifications",
    "duties",
    "created_at",
    "activation_date",
    "application_end_date",
    "updated_at",
    "is_active",
    "is_expired",
    "is_featured",
    "visibility",
    "scraped_at",
]

TRABAJO_FIELDNAMES = [
    "job_id",
    "source_id",
    "identifier",
    "job_title",
    "job_url",
    "canonical_url",
    "company_name",
    "company_logo_url",
    "location_raw",
    "city",
    "region",
    "country",
    "employment_type",
    "employment_type_schema",
    "work_mode",
    "salary_raw",
    "salary_currency",
    "salary_min",
    "salary_max",
    "salary_period",
    "date_posted",
    "valid_through",
    "posted_relative",
    "direct_apply",
    "category",
    "category_url",
    "description",
    "search_keyword",
    "listing_page_number",
    "listing_snippet",
    "scraped_at",
]

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n\s*\n+")


def strip_html(value):
    """Convert an HTML fragment (e.g. job.description) into clean plain text."""
    if value is None:
        return ""
    if not isinstance(value, str):
        return value

    # Normalize common block-level tags into newlines before stripping,
    # so list items / paragraphs don't get smashed together.
    text = re.sub(r"(?i)<\s*(br|/li|/p|/ul|/ol)\s*/?\s*>", "\n", value)
    text = re.sub(r"(?i)<\s*li[^>]*>", "- ", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = _WHITESPACE_RE.sub(" ", text)
    text = _BLANK_LINES_RE.sub("\n", text)
    return text.strip()


def get_nested(d, path, default=None):
    """Safely walk a dotted path (e.g. 'company.code') through nested dicts."""
    current = d
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current if current is not None else default


def blank_none(row: dict) -> dict:
    """Normalize None -> "" so CSV cells are blank instead of literal "None"."""
    for key, value in row.items():
        if value is None:
            row[key] = ""
    return row


def file_scraped_at(path: Path) -> str:
    """Use the file's modification time as a proxy for when it was scraped."""
    try:
        ts = os.path.getmtime(path)
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except OSError:
        return ""


# --------------------------------------------------------------------------
# Source: Kalibrr
# --------------------------------------------------------------------------

def build_kalibrr_job_url(company_code, job_id, slug):
    if not company_code or not job_id or not slug:
        return ""
    return f"https://www.kalibrr.com/c/{company_code}/jobs/{job_id}/{slug}"


def extract_kalibrr_row(data: dict, source_path: Path) -> dict | None:
    page_props = data.get("pageProps")
    if not isinstance(page_props, dict):
        log.warning("Skipping %s: no 'pageProps' found.", source_path.name)
        return None

    job = page_props.get("job")
    if not isinstance(job, dict):
        log.warning("Skipping %s: no 'pageProps.job' found.", source_path.name)
        return None

    company_code = get_nested(job, "company.code")
    job_id = job.get("id")
    slug = job.get("slug")

    row = {
        "job_id": job_id,
        "job_title": job.get("name"),
        "slug": slug,
        "job_url": build_kalibrr_job_url(company_code, job_id, slug),
        "company_name": get_nested(job, "company.name"),
        "company_code": company_code,
        "company_industry": get_nested(job, "company.industry"),
        "company_url": get_nested(job, "company.url"),
        "company_verified": get_nested(job, "company.verified"),
        "function": job.get("function"),
        "tenure": job.get("tenure"),
        "number_of_openings": job.get("numberOfOpenings"),
        "work_experience_code": job.get("workExperience"),
        "months_work_experience": job.get("monthsWorkExperience"),
        "education_level_code": job.get("educationLevel"),
        "open_to_fresh_grads": job.get("isOpenToFreshGrads"),
        "is_hybrid": job.get("isHybrid"),
        "is_work_from_home": job.get("isWorkFromHome"),
        "city": get_nested(job, "googleLocation.addressComponents.city"),
        "region": get_nested(job, "googleLocation.addressComponents.region"),
        "country": get_nested(job, "googleLocation.addressComponents.country"),
        "formatted_address": get_nested(job, "googleLocation.formattedAddress"),
        "latitude": get_nested(job, "googleLocation.latitude"),
        "longitude": get_nested(job, "googleLocation.longitude"),
        "salary_shown": job.get("salaryShown"),
        "base_salary": job.get("baseSalary"),
        "maximum_salary": job.get("maximumSalary"),
        "salary_currency": job.get("salaryCurrency"),
        "salary_interval": job.get("salaryInterval"),
        "description": strip_html(job.get("description")),
        "qualifications": strip_html(job.get("qualifications")),
        "duties": strip_html(job.get("duties")),
        "created_at": job.get("createdAt"),
        "activation_date": job.get("activationDate"),
        "application_end_date": job.get("applicationEndDate"),
        "updated_at": job.get("updatedAt"),
        "is_active": job.get("active"),
        "is_expired": page_props.get("isExpired"),
        "is_featured": job.get("isFeatured"),
        "visibility": job.get("visibility"),
        "scraped_at": file_scraped_at(source_path),
    }
    return blank_none(row)


# --------------------------------------------------------------------------
# Source: Trabajo
# --------------------------------------------------------------------------

def extract_trabajo_row(data: dict, source_path: Path) -> dict | None:
    # Every file written by trabajo_scraper.py has a job_id and a title.
    if not isinstance(data, dict) or not data.get("job_id") or not data.get("title"):
        log.warning("Skipping %s: not a Trabajo job file (no 'job_id'/'title').",
                    source_path.name)
        return None

    # Prefer the plain text description the scraper produced; fall back to HTML.
    description = data.get("description_text") or strip_html(data.get("description_html"))

    row = {
        "job_id": data.get("job_id"),
        "source_id": data.get("source_id"),
        "identifier": data.get("identifier"),
        "job_title": data.get("title"),
        "job_url": data.get("url"),
        "canonical_url": data.get("canonical_url"),
        "company_name": get_nested(data, "company.name"),
        "company_logo_url": get_nested(data, "company.logo_url"),
        "location_raw": get_nested(data, "location.raw"),
        "city": get_nested(data, "location.locality"),
        "region": get_nested(data, "location.region"),
        "country": get_nested(data, "location.country"),
        "employment_type": get_nested(data, "employment_type.raw"),
        "employment_type_schema": get_nested(data, "employment_type.schema"),
        "work_mode": data.get("work_mode"),
        "salary_raw": get_nested(data, "salary.raw"),
        "salary_currency": get_nested(data, "salary.currency"),
        "salary_min": get_nested(data, "salary.min"),
        "salary_max": get_nested(data, "salary.max"),
        "salary_period": get_nested(data, "salary.period"),
        "date_posted": data.get("date_posted"),
        "valid_through": data.get("valid_through"),
        "posted_relative": data.get("posted_relative"),
        "direct_apply": data.get("direct_apply"),
        "category": get_nested(data, "category.name"),
        "category_url": get_nested(data, "category.url"),
        "description": description,
        "search_keyword": data.get("search_keyword"),
        "listing_page_number": get_nested(data, "listing.page_number"),
        "listing_snippet": get_nested(data, "listing.snippet"),
        # The Trabajo scraper records its own UTC timestamp; fall back to file mtime.
        "scraped_at": data.get("scraped_at") or file_scraped_at(source_path),
    }
    return blank_none(row)


# --------------------------------------------------------------------------
# Source registry
# --------------------------------------------------------------------------

SOURCES = {
    "kalibrr": {
        "fieldnames": KALIBRR_FIELDNAMES,
        "extractor": extract_kalibrr_row,
        "default_input": "./kalibrr_jobs",
        "default_output": "./kalibrr_jobs.csv",
    },
    "trabajo": {
        "fieldnames": TRABAJO_FIELDNAMES,
        "extractor": extract_trabajo_row,
        "default_input": "./trabajo_jobs",
        "default_output": "./trabajo_jobs.csv",
    },
}


# --------------------------------------------------------------------------
# Main compile routine
# --------------------------------------------------------------------------

def compile_to_csv(source: str, input_dir: Path, output_csv: Path) -> None:
    cfg = SOURCES[source]
    fieldnames, extractor = cfg["fieldnames"], cfg["extractor"]

    if not input_dir.is_dir():
        log.error("Input directory does not exist: %s", input_dir)
        sys.exit(1)

    json_files = sorted(input_dir.glob("*.json"))
    if not json_files:
        log.error("No .json files found in %s", input_dir)
        sys.exit(1)

    log.info("Source: %s | Found %d JSON file(s) in %s", source, len(json_files), input_dir)

    rows = []
    skipped = 0

    for path in json_files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Skipping %s: could not read/parse JSON (%s)", path.name, exc)
            skipped += 1
            continue

        row = extractor(data, path)
        if row is None:
            skipped += 1
            continue

        rows.append(row)

    if not rows:
        log.error(
            "No valid job rows extracted; nothing to write. "
            "Is --source %r the right one for the files in %s?",
            source, input_dir,
        )
        sys.exit(1)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    log.info(
        "Done. Wrote %d row(s) to %s (skipped %d file(s)).",
        len(rows), output_csv, skipped,
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compile scraped job JSON files (Kalibrr or Trabajo) into a single CSV."
    )
    parser.add_argument(
        "--source", "-s", choices=sorted(SOURCES), default="kalibrr",
        help="Which scraper produced the JSON files (default: kalibrr).",
    )
    parser.add_argument(
        "--input-dir", "-i", default=None,
        help="Folder containing the individual job JSON files "
             "(default: ./kalibrr_jobs or ./trabajo_jobs, depending on --source).",
    )
    parser.add_argument(
        "--output-csv", "-o", default=None,
        help="Path to write the compiled CSV file to "
             "(default: ./kalibrr_jobs.csv or ./trabajo_jobs.csv, depending on --source).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = SOURCES[args.source]
    input_dir = Path(args.input_dir or cfg["default_input"])
    output_csv = Path(args.output_csv or cfg["default_output"])
    compile_to_csv(args.source, input_dir, output_csv)


if __name__ == "__main__":
    main()
