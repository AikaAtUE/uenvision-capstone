#!/usr/bin/env python3
"""
Kalibrr Job JSON -> CSV Compiler
==================================

Reads every individual job-posting JSON file saved by kalibrr_scraper.py
(the *.json files under a folder like ./kalibrr_jobs) and compiles them
into a single CSV file, using the finalized column schema.

Usage
-----
    python compile_jobs_to_csv.py --input-dir ./kalibrr_jobs --output-csv kalibrr_jobs.csv

    # Re-run any time after scraping more jobs -- it always rebuilds the
    # CSV from scratch from whatever *.json files currently exist.
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
# Final CSV column schema (order matters -- this is the header row)
# --------------------------------------------------------------------------

FIELDNAMES = [
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


def build_job_url(company_code, job_id, slug):
    if not company_code or not job_id or not slug:
        return ""
    return f"https://www.kalibrr.com/c/{company_code}/jobs/{job_id}/{slug}"


def file_scraped_at(path: Path) -> str:
    """Use the file's modification time as a proxy for when it was scraped."""
    try:
        ts = os.path.getmtime(path)
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except OSError:
        return ""


def extract_row(data: dict, source_path: Path) -> dict | None:
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
        "job_url": build_job_url(company_code, job_id, slug),
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

    # Normalize None -> "" so CSV cells are blank instead of literal "None"
    for key, value in row.items():
        if value is None:
            row[key] = ""

    return row


# --------------------------------------------------------------------------
# Main compile routine
# --------------------------------------------------------------------------

def compile_to_csv(input_dir: Path, output_csv: Path) -> None:
    if not input_dir.is_dir():
        log.error("Input directory does not exist: %s", input_dir)
        sys.exit(1)

    json_files = sorted(input_dir.glob("*.json"))
    if not json_files:
        log.error("No .json files found in %s", input_dir)
        sys.exit(1)

    log.info("Found %d JSON file(s) in %s", len(json_files), input_dir)

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

        row = extract_row(data, path)
        if row is None:
            skipped += 1
            continue

        rows.append(row)

    if not rows:
        log.error("No valid job rows extracted; nothing to write.")
        sys.exit(1)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
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
        description="Compile scraped Kalibrr job JSON files into a single CSV."
    )
    parser.add_argument(
        "--input-dir", "-i", default="./kalibrr_jobs",
        help="Folder containing the individual job JSON files (default: ./kalibrr_jobs).",
    )
    parser.add_argument(
        "--output-csv", "-o", default="./kalibrr_jobs.csv",
        help="Path to write the compiled CSV file to (default: ./kalibrr_jobs.csv).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    compile_to_csv(Path(args.input_dir), Path(args.output_csv))


if __name__ == "__main__":
    main()
