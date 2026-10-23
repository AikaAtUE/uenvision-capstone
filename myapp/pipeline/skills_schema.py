"""
The one column layout of data/extracted_skills.csv, shared by every job source.

Kalibrr and Trabajo name the same things differently (Kalibrr "tenure" = Trabajo
"employment_type", and so on). Whatever the source, an extracted row is written with
these columns, in this order; a column the source doesn't have is left blank.

Stdlib only: imported by extract_skills_gemini.py (run as a script) and by manager.py.
"""

UNIVERSAL_COLUMNS = [
    "job_id", "job_name", "source",
    "company_name", "company_id", "company_industry", "company_url", "company_logo_url", "company_verified",
    "job_url", "function", "tenure", "work_mode", "number_of_openings", "months_work_experience",
    "education_level_code", "open_to_fresh_grads", "is_hybrid", "is_work_from_home",
    "city", "region", "country", "formatted_address",
    "salary_shown", "base_salary", "maximum_salary", "salary_currency", "salary_interval",
    "date", "is_active", "is_expired",
    "hard_skills", "hard_skills_raw", "soft_skills", "certifications_or_licenses", "experience_level", "education",
]

# Source-specific / older column name -> universal name
ALIASES = {
    "job_title": "job_name",
    "company_code": "company_id",
    "created_at": "date",            # Kalibrr
    "date_posted": "date",           # Trabajo
    "employment_type": "tenure",
    "category": "function",
    "location_raw": "formatted_address",
    "salary_min": "base_salary",
    "salary_max": "maximum_salary",
    "salary_period": "salary_interval",
}

# No longer exported
DROPPED = {"activation_date", "application_end_date", "valid_through"}

# What to read from each source's compiled CSV
SOURCE_CONFIG = {
    "kalibrr": {
        "text_columns": ["description", "qualifications", "duties"],
        "company_cols": ["company_name", "company_code", "company_industry", "company_url", "company_verified"],
        "job_cols": ["job_url", "function", "tenure", "number_of_openings", "months_work_experience",
                     "education_level_code", "open_to_fresh_grads", "is_hybrid", "is_work_from_home",
                     "city", "region", "country", "formatted_address", "salary_shown", "base_salary",
                     "maximum_salary", "salary_currency", "salary_interval", "created_at",
                     "is_active", "is_expired"],
    },
    "trabajo": {
        "text_columns": ["description"],
        "company_cols": ["company_name", "company_logo_url"],
        "job_cols": ["job_url", "location_raw", "city", "region", "country", "employment_type", "work_mode",
                     "salary_currency", "salary_min", "salary_max", "salary_period", "date_posted", "category"],
    },
}


def _blank(v):
    return v is None or (isinstance(v, str) and not v.strip())


def _truthy(v):
    return v is True or (isinstance(v, str) and v.strip().lower() in ("true", "1", "yes"))


def normalize_record(rec: dict) -> dict:
    """Rename / drop columns to the universal layout and return them in universal order."""
    out = {}
    for k, v in rec.items():
        if k in DROPPED:
            continue
        k = ALIASES.get(k, k)
        if k not in out or _blank(out[k]):
            out[k] = v
    if _blank(out.get("work_mode")):
        if _truthy(out.get("is_work_from_home")):
            out["work_mode"] = "Work from home"
        elif _truthy(out.get("is_hybrid")):
            out["work_mode"] = "Hybrid"
        elif "is_hybrid" in out or "is_work_from_home" in out:
            out["work_mode"] = "On-site"
    ordered = {c: out.get(c) for c in UNIVERSAL_COLUMNS}
    ordered.update({k: v for k, v in out.items() if k not in ordered})
    return ordered


# ---------------------------------------------------------------------------
# Skills-only CSVs: data/hard_skills.csv and data/soft_skills.csv
#   one row per (job, skill):  job_name, job_level, skill
# ---------------------------------------------------------------------------
import csv
import os
import tempfile

SKILL_CSVS = {"hard_skills": "hard_skills.csv", "soft_skills": "soft_skills.csv"}
SKILL_CSV_COLUMNS = ["job_name", "job_level", "skill"]
NO_LEVEL = "Not specified"


def split_skills(value):
    """A skills cell: either a list (resume JSON) or 'a; b; c' (CSV)."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = str(value).split(";")
    return [" ".join(str(x).split()) for x in items if x is not None and str(x).strip()]


def write_skill_csvs(records, out_dir):
    """records: dicts with job_name, experience_level, hard_skills, soft_skills."""
    for col, filename in SKILL_CSVS.items():
        path = os.path.join(out_dir, filename)
        fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=filename + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f, lineterminator="\r\n")
                w.writerow(SKILL_CSV_COLUMNS)
                for r in records:
                    level = " ".join(str(r.get("experience_level") or "").split()) or NO_LEVEL
                    seen = set()
                    for skill in split_skills(r.get(col)):
                        if skill.lower() in seen:
                            continue
                        seen.add(skill.lower())
                        w.writerow([r.get("job_name") or r.get("job_title") or "", level, skill])
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
