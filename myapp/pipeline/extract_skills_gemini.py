#!/usr/bin/env python3
"""
Skill Extraction from job postings using the (free) Google Gemini API
---------------------------------------------------------------------
- Up to 100 jobs per prompt (default 20)
- API keys are read from api_keys.txt (one per line); when a key hits its
  daily quota or is invalid, the script moves on to the next line
- Output CSV/JSON include job info + company info + extracted skills
- Saves after every batch and resumes where it stopped

Setup:   pip install google-genai pandas pydantic tqdm
Run:     python extract_skills_gemini.py jobs.csv --output-dir results
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import List, Optional

import pandas as pd
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field
from tqdm import tqdm

from dedupe_trabajo import merged_job_ids
from skills_schema import (ALIASES, JOB_FLAG_COLUMNS, SOURCE_CONFIG, UNIVERSAL_COLUMNS, normalize_record,
                           write_skill_csvs)

# ====================== DEFAULTS ======================
# Every value can be overridden from the command line (see --help).
CSV_PATH = "kalibrr_jobs_2.csv"
API_KEYS_FILE = "api_keys.txt"                # one Gemini API key per line
OUTPUT_PREFIX = "jobs_with_skills"            # -> <prefix>.csv and <prefix>.json

# Older models (e.g. gemini-2.5-flash) are being shut down and return "model not found".
MODEL = "gemini-3.5-flash-lite"
BATCH_SIZE = 20                               # default jobs per prompt
MAX_BATCH_SIZE = 100                          # hard cap
MAX_CHARS_PER_JOB = 2500
MAX_OUTPUT_TOKENS = 32000
RPM = 5                                       # free-tier requests/minute (5 is safest)
MAX_RETRIES = 3                               # retries per key for temporary errors

# CSV columns
COL_ID = "job_id"
COL_TITLE = "job_title"
TEXT_COLUMNS = ["description", "qualifications", "duties"]   # text sent to the model

# Which CSV columns are read per source, and how they are renamed, lives in skills_schema.py
# so that Kalibrr and Trabajo rows end up in the same universal layout.
RENAME = {COL_TITLE: "job_name", **ALIASES}
# ======================================================

OUTPUT_CSV = OUTPUT_PREFIX + ".csv"
OUTPUT_JSON = OUTPUT_PREFIX + ".json"          # source of truth for resume
DEBUG_LOG = None                               # set by --debug
SKILL_COLS = ["hard_skills", "soft_skills", "certifications_or_licenses",
              "experience_level", "education"]


# ---------- Structured output schema (no defaults: Gemini's schema dislikes them) ----------
# The yes/no questions Gemini answers for every job: schema field -> CSV column (JOB_FLAG_COLUMNS).
FLAG_DESCRIPTIONS = {
    "is_tech_job": "true if this is a technology / IT job: the work itself is software, IT, data, networking, "
                   "cybersecurity, cloud, QA, IT support or similar. false for non-tech work (sales, HR, "
                   "accounting, customer service, marketing...), even at a tech company",
    "computer_science": "true if a BS Computer Science graduate is a good fit: software engineering, "
                        "programming, algorithms, data science, AI / machine learning, research and similar. "
                        "false if is_tech_job is false",
    "information_technology": "true if a BS Information Technology graduate is a good fit: systems and network "
                              "administration, IT support, web development, databases, cloud, cybersecurity, "
                              "QA and similar. false if is_tech_job is false",
}


class JobFlags(BaseModel):
    job_id: str = Field(description="The job id exactly as given in the input")
    is_tech_job: bool = Field(description=FLAG_DESCRIPTIONS["is_tech_job"])
    computer_science: bool = Field(description=FLAG_DESCRIPTIONS["computer_science"])
    information_technology: bool = Field(description=FLAG_DESCRIPTIONS["information_technology"])


class BatchFlags(BaseModel):
    results: List[JobFlags] = Field(
        description="Exactly one entry per job in the input, in the same order")


class JobSkills(BaseModel):
    job_id: str = Field(description="The job id exactly as given in the input")
    is_tech_job: bool = Field(description=FLAG_DESCRIPTIONS["is_tech_job"])
    computer_science: bool = Field(description=FLAG_DESCRIPTIONS["computer_science"])
    information_technology: bool = Field(description=FLAG_DESCRIPTIONS["information_technology"])
    hard_skills: List[str] = Field(
        description="Technical skills, languages, frameworks, tools, databases, cloud platforms, "
                    "methodologies (e.g. Python, React, AWS, Agile, CI/CD)")
    soft_skills: List[str] = Field(
        description="Interpersonal skills (e.g. communication, leadership, problem-solving)")
    certifications_or_licenses: List[str] = Field(
        description="Certifications, licenses or professional credentials mentioned; empty list if none")
    experience_level: Optional[str] = Field(
        description="One of 'Entry', 'Junior', 'Mid', 'Senior', 'Lead/Manager', or null")
    education: Optional[str] = Field(
        description="Minimum education requirement if clearly stated, else null")


class BatchExtraction(BaseModel):
    results: List[JobSkills] = Field(
        description="Exactly one entry per job in the input, in the same order")


# ---------- API key management ----------
class AllKeysExhausted(Exception):
    pass


class FatalError(Exception):
    pass


class KeyPool:
    """Cycles through api_keys.txt, one line per key."""

    def __init__(self, path: str):
        p = Path(path)
        # Extra keys may also come from the GEMINI_API_KEYS environment variable.
        env_keys = [k.strip() for k in os.environ.get("GEMINI_API_KEYS", "").replace(",", "\n").splitlines()
                    if k.strip()]
        if not p.exists() and not env_keys:
            raise FileNotFoundError(f"{path} not found. Put one Gemini API key per line in it.")
        file_keys = [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()
                     if ln.strip() and not ln.strip().startswith("#")] if p.exists() else []
        self.keys = list(dict.fromkeys(file_keys + env_keys))
        if not self.keys:
            raise ValueError(f"{path} contains no API keys.")
        self.idx = 0
        self._make_client()

    def _make_client(self):
        self.client = genai.Client(api_key=self.keys[self.idx])

    @property
    def label(self) -> str:
        return f"key #{self.idx + 1}/{len(self.keys)} (…{self.keys[self.idx][-4:]})"

    def next_key(self) -> bool:
        if self.idx + 1 >= len(self.keys):
            return False
        self.idx += 1
        self._make_client()
        print(f"\n[KEY] Switched to {self.label}")
        return True


def classify_error(e: Exception) -> str:
    """Returns 'rotate' | 'wait' | 'retry' | 'fatal'."""
    code = getattr(e, "code", None)
    low = str(e).lower()
    squashed = re.sub(r"[\s_]", "", low)

    if code == 429 or "resource_exhausted" in low:
        if "limit: 0" in low:
            return "fatal"            # model isn't offered on the free tier at all
        if "perday" in squashed or "daily" in low:
            return "rotate"           # daily quota used up -> next key
        return "wait"                 # per-minute limit -> wait and retry
    if code in (401, 403):
        return "rotate"
    if code == 400 and ("api key" in low or "api_key" in low or "expired" in low):
        return "rotate"
    if code in (400, 404):
        return "fatal"                # bad request / unknown model: another key won't help
    return "retry"                    # 5xx, network errors, etc.


def retry_delay(e: Exception, default: float = 60.0) -> float:
    m = (re.search(r"retry in ([\d.]+)\s*s", str(e), re.I)
         or re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s", str(e)))
    return min(float(m.group(1)) + 1, 120.0) if m else default


# ---------- Text pre-processing ----------
def clean_text(text) -> str:
    if not isinstance(text, str) or not text.strip():
        return ""
    text = re.sub(r"[\u200b\u200c\u200d\ufeff\xa0]", " ", text)
    text = re.sub(r"\r\n|\r", "\n", text)
    text = re.sub(r"^[\s\-\*\u2022]+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def prepare_job_text(row: dict) -> str:
    parts = [clean_text(row.get(c)) for c in TEXT_COLUMNS]
    combined = "\n".join(p for p in parts if p)
    if len(combined) > MAX_CHARS_PER_JOB:
        combined = combined[:MAX_CHARS_PER_JOB].rsplit(" ", 1)[0] + " ..."
    return combined


def to_py(v):
    """Make a pandas/numpy value JSON-safe (NaN -> None, numpy -> python)."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v.item() if hasattr(v, "item") else v


# ---------- Gemini calls ----------
SYSTEM_PROMPT = (
    "You are an expert technical recruiter. You will receive several job postings, "
    "each wrapped in <job id=...> tags. For EACH job, extract only concrete, actionable skills. "
    "Be precise and avoid generic phrases. Use the most common professional form of a skill "
    "(e.g. 'React' not 'React.js framework'). Do not invent skills that are not mentioned. "
    "Return exactly one result per job, copying each job_id exactly as given. "
    "Never mix skills between different jobs. "
    "Also answer, for each job, whether it is a tech job and whether it fits a BS Computer Science "
    "and/or a BS Information Technology graduate (both can be true)."
)

# For jobs saved before the yes/no columns existed: only the yes/no answers, skills are left alone.
FLAGS_PROMPT = (
    "You are an expert technical recruiter. You will receive several job postings, "
    "each wrapped in <job id=...> tags. For EACH job, answer whether it is a tech job and whether it "
    "fits a BS Computer Science and/or a BS Information Technology graduate (both can be true). "
    "Return exactly one result per job, copying each job_id exactly as given."
)


def build_prompt(batch: List[dict]) -> str:
    return "\n\n".join(
        f'<job id="{b["job_id"]}">\nTitle: {b["title"]}\n{b["text"]}\n</job>' for b in batch)


class Throttle:
    """Keeps us under the free-tier requests-per-minute limit."""

    def __init__(self, rpm: float):
        self.interval = 60.0 / rpm
        self.last = 0.0

    def wait(self):
        gap = self.interval - (time.time() - self.last)
        if gap > 0:
            time.sleep(gap)
        self.last = time.time()


def log_debug(msg: str):
    if DEBUG_LOG:
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n" + "-" * 60 + "\n")


def describe_response(resp) -> str:
    """Short description of what the model returned, for error messages."""
    try:
        cand = resp.candidates[0] if resp.candidates else None
        reason = getattr(cand, "finish_reason", None)
        fb = getattr(resp, "prompt_feedback", None)
        head = (resp.text or "")[:200].replace("\n", " ")
        return f"finish_reason={reason} prompt_feedback={fb} text_head={head!r}"
    except Exception as ex:  # never let diagnostics crash the run
        return f"(could not describe response: {ex})"


def call_once(pool: KeyPool, throttle: Throttle, batch: List[dict],
              schema=BatchExtraction, system: str = SYSTEM_PROMPT) -> Optional[dict]:
    """One batch -> {job_id: dict}, or None if it failed repeatedly (caller may split)."""
    prompt = build_prompt(batch)
    expected = [b["job_id"] for b in batch]
    retries = 0
    while True:
        throttle.wait()
        resp = None
        try:
            # Note: no temperature - Gemini 3.x ignores it (some 3.x models reject it).
            resp = pool.client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=schema,
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                ),
            )
            log_debug(f"REQUEST ids={expected}\nRESPONSE: {describe_response(resp)}\nFULL TEXT:\n{resp.text}")

            parsed = getattr(resp, "parsed", None)
            if parsed is None:   # fall back to parsing the raw text
                txt = re.sub(r"^```(?:json)?|```$", "", (resp.text or "").strip(), flags=re.M).strip()
                parsed = schema.model_validate_json(txt)
            if not parsed.results:
                raise ValueError("model returned zero results")

            res = {str(r.job_id).strip(): r.model_dump() for r in parsed.results}
            if not all(i in res for i in expected) and len(parsed.results) == len(batch):
                # ids came back altered: trust the order instead (we asked for the same order)
                print(f"\n[INFO] job_ids in the reply didn't match; matching by position instead")
                res = {expected[i]: parsed.results[i].model_dump() for i in range(len(batch))}
            return res

        except Exception as e:
            kind = classify_error(e)
            if kind == "fatal":
                raise FatalError(f"{type(e).__name__}: {str(e)[:500]}")
            if kind == "rotate":
                print(f"\n[KEY] {pool.label} unusable (quota/invalid): {str(e)[:120]}")
                if not pool.next_key():
                    raise AllKeysExhausted("All API keys in the keys file are exhausted/invalid.")
                retries = 0
                continue

            detail = describe_response(resp) if resp is not None else ""
            retries += 1
            if retries > MAX_RETRIES:
                if kind == "wait":      # still rate-limited after waiting: try the next key
                    print(f"\n[KEY] {pool.label} keeps hitting the rate limit")
                    if pool.next_key():
                        retries = 0
                        continue
                    raise AllKeysExhausted("All API keys are rate limited / exhausted.")
                print(f"\n[WARN] Batch of {len(batch)} failed after retries: {str(e)[:200]} {detail}")
                return None
            wait = retry_delay(e) if kind == "wait" else 5 * 2 ** (retries - 1)
            print(f"\n[WARN] {type(e).__name__}: {str(e)[:200]} {detail} -> retry {retries} in {wait:.0f}s")
            time.sleep(wait)


def extract_batch(pool: KeyPool, throttle: Throttle, batch: List[dict], depth: int = 0,
                  schema=BatchExtraction, system: str = SYSTEM_PROMPT) -> dict:
    """Like call_once, but if a batch keeps failing it is split in half (up to 2 levels) and retried."""
    res = call_once(pool, throttle, batch, schema, system)
    if res is not None:
        return res
    if len(batch) == 1 or depth >= 2:
        return {}
    mid = len(batch) // 2
    print(f"[INFO] Splitting batch ({mid} + {len(batch) - mid})")
    out = extract_batch(pool, throttle, batch[:mid], depth + 1, schema, system)
    out.update(extract_batch(pool, throttle, batch[mid:], depth + 1, schema, system))
    return out


def add_missing_flags(pool: KeyPool, throttle: Throttle, results: List[dict], source_rows: dict) -> int:
    """Fill isTechJob / COMPUTER SCIENCE / INFORMATION TECHNOLOGY for saved jobs that don't have them yet
    (saved before these columns existed, or with no description). Their skills are not touched.
    source_rows: job_id -> row of the input CSV. Returns how many jobs got answers."""
    todo = [r for r in results
            if any(r.get(col) in (None, "") for col in JOB_FLAG_COLUMNS.values()) and str(r["job_id"]) in source_rows]
    if not todo:
        return 0
    print(f"Answering the tech job / CS / IT questions for {len(todo)} job(s) saved without them ...")
    filled = 0
    for i in range(0, len(todo), BATCH_SIZE):
        chunk = todo[i:i + BATCH_SIZE]
        batch = [{"job_id": str(r["job_id"]), "title": to_py(source_rows[str(r["job_id"])].get(COL_TITLE)) or "",
                  "text": prepare_job_text(source_rows[str(r["job_id"])])} for r in chunk]
        got = extract_batch(pool, throttle, batch, schema=BatchFlags, system=FLAGS_PROMPT)
        for r in chunk:
            ans = got.get(str(r["job_id"]))
            if ans:
                r.update({col: ans[field] for field, col in JOB_FLAG_COLUMNS.items()})
                filled += 1
        save_outputs(results)
    return filled


# ---------- Output ----------
def save_outputs(results: List[dict]):
    if not results:      # never overwrite/create empty output files
        return
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    flat = []
    for r in results:
        r = dict(r)
        for c in ("hard_skills", "hard_skills_raw", "soft_skills", "certifications_or_licenses"):
            r[c] = "; ".join(r.get(c) or [])
        flat.append(r)
    cols = list(UNIVERSAL_COLUMNS) + [c for c in dict.fromkeys(k for r in flat for k in r) if c not in UNIVERSAL_COLUMNS]
    pd.DataFrame(flat).reindex(columns=cols).to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    try:    # hard_skills.csv / soft_skills.csv sit next to the main CSV
        write_skill_csvs(results, os.path.dirname(os.path.abspath(OUTPUT_CSV)))
    except OSError as e:
        print(f"[WARN] Couldn't write the hard/soft skills CSVs: {e}")


def parse_list(s: str) -> List[str]:
    return [c.strip() for c in s.split(",") if c.strip()]


def parse_args():
    ap = argparse.ArgumentParser(description="Extract skills from job postings in a CSV using Gemini.")
    ap.add_argument("csv", nargs="?", default=CSV_PATH, help="input CSV file")
    ap.add_argument("--keys", default=API_KEYS_FILE, help="file with one API key per line")
    ap.add_argument("--output", default=OUTPUT_PREFIX, help="output name prefix")
    ap.add_argument("--output-dir", default=".", help="output folder (created if missing)")
    ap.add_argument("--json-dir", default=None,
                    help="folder for the resume-state JSON (default: same as --output-dir)")
    ap.add_argument("--source-label", default=None,
                    help="if set, adds a 'source' column with this value (e.g. kalibrr / trabajo)")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--batch-size", type=int, default=BATCH_SIZE, help=f"jobs per prompt (max {MAX_BATCH_SIZE})")
    ap.add_argument("--rpm", type=float, default=RPM, help="requests per minute to stay under")
    ap.add_argument("--limit", type=int, default=None, help="only process the first N jobs")
    ap.add_argument("--id-col", default=COL_ID)
    ap.add_argument("--title-col", default=COL_TITLE)
    ap.add_argument("--text-columns", default=None,
                    help="comma-separated columns sent to the model (default: depends on --source-label)")
    ap.add_argument("--company-cols", default=None,
                    help="comma-separated company columns to copy into the output (default: by source)")
    ap.add_argument("--job-cols", default=None,
                    help="comma-separated job columns to copy into the output (default: by source)")
    ap.add_argument("--max-chars", type=int, default=MAX_CHARS_PER_JOB)
    ap.add_argument("--debug", action="store_true",
                    help="write every raw model reply to <output>_debug.log")
    return ap.parse_args()


def main():
    global MODEL, BATCH_SIZE, MAX_CHARS_PER_JOB, TEXT_COLUMNS, COL_ID, COL_TITLE
    global OUTPUT_CSV, OUTPUT_JSON, RENAME, DEBUG_LOG

    a = parse_args()
    MODEL = a.model
    BATCH_SIZE = max(1, min(a.batch_size, MAX_BATCH_SIZE))
    MAX_CHARS_PER_JOB = a.max_chars
    cfg = SOURCE_CONFIG.get(a.source_label or "kalibrr", SOURCE_CONFIG["kalibrr"])
    TEXT_COLUMNS = parse_list(a.text_columns) if a.text_columns else list(cfg["text_columns"])
    old_title = COL_TITLE
    COL_ID, COL_TITLE = a.id_col, a.title_col
    RENAME = {COL_TITLE: "job_name", **ALIASES}
    os.makedirs(a.output_dir, exist_ok=True)
    OUTPUT_CSV = os.path.join(a.output_dir, a.output + ".csv")
    json_dir = a.json_dir or a.output_dir
    os.makedirs(json_dir, exist_ok=True)
    OUTPUT_JSON = os.path.join(json_dir, a.output + ".json")
    if a.debug:
        DEBUG_LOG = os.path.join(a.output_dir, a.output + "_debug.log")
        print(f"Debug log: {DEBUG_LOG}")

    print(f"Loading {a.csv} ...")
    df = pd.read_csv(a.csv)
    print(f"Columns ({len(df.columns)}): {', '.join(df.columns)}\n")

    missing = [c for c in [COL_ID, COL_TITLE] + TEXT_COLUMNS if c not in df.columns]
    if missing:
        raise SystemExit(f"Column(s) not found in CSV: {missing}\nAvailable: {list(df.columns)}")
    company_cols_all = parse_list(a.company_cols) if a.company_cols else cfg["company_cols"]
    job_cols_all = parse_list(a.job_cols) if a.job_cols else cfg["job_cols"]
    company_cols = [c for c in company_cols_all if c in df.columns]
    job_cols = [c for c in job_cols_all if c in df.columns and c not in (COL_ID, COL_TITLE)]
    skipped = [c for c in company_cols_all + job_cols_all if c not in df.columns]
    if skipped:
        print(f"Note: columns not in this CSV, skipped: {skipped}\n")

    dupes = int(df[COL_ID].duplicated().sum())
    if dupes:
        print(f"Dropping {dupes} duplicate {COL_ID} row(s)")
        df = df.drop_duplicates(subset=COL_ID, keep="first")
    if a.limit:
        df = df.head(a.limit)
    all_rows = df.to_dict("records")

    results: List[dict] = []
    if Path(OUTPUT_JSON).exists():
        results = [normalize_record(r) for r in json.loads(Path(OUTPUT_JSON).read_text(encoding="utf-8"))]
        if a.source_label == "trabajo" and "merged_job_ids" in df.columns:
            # Postings the Trabajo compile step merged into another row: drop skills extracted earlier
            # for those copies, so each ad is counted once in the skills datasets.
            dropped = merged_job_ids(df.to_dict("records"))
            before = len(results)
            results = [r for r in results
                       if not (r.get("source") == "trabajo" and str(r["job_id"]) in dropped)]
            if len(results) < before:
                print(f"Removed {before - len(results)} previously extracted duplicate Trabajo posting(s)")
        done = {str(r["job_id"]) for r in results}
        df = df[~df[COL_ID].astype(str).isin(done)]
        print(f"Resuming: {len(done)} done, {len(df)} remaining")
    source_rows = {str(to_py(r[COL_ID])): r for r in all_rows}
    needs_flags = any(any(r.get(col) in (None, "") for col in JOB_FLAG_COLUMNS.values())
                      and str(r["job_id"]) in source_rows for r in results)
    if df.empty and not needs_flags:
        save_outputs(results)      # also rewrites the CSV with the current columns
        print("Nothing to do.")
        return

    pool = KeyPool(a.keys)
    throttle = Throttle(a.rpm)
    print(f"Loaded {len(pool.keys)} API key(s). Using {pool.label}. Model: {MODEL}")

    rows = df.to_dict("records")
    total = len(results) + len(rows)
    n_batches = (len(rows) + BATCH_SIZE - 1) // BATCH_SIZE

    failed_in_a_row = 0
    try:
        for b in tqdm(range(n_batches), desc="Batches"):
            chunk = rows[b * BATCH_SIZE:(b + 1) * BATCH_SIZE]
            batch, meta = [], {}
            for row in chunk:
                jid = str(to_py(row[COL_ID]))
                text = prepare_job_text(row)
                meta[jid] = (row, bool(text))
                if text:
                    batch.append({"job_id": jid, "title": to_py(row.get(COL_TITLE)) or "", "text": text})

            extracted = extract_batch(pool, throttle, batch) if batch else {}
            got = sum(1 for x in batch if x["job_id"] in extracted)
            tqdm.write(f"Batch {b + 1}/{n_batches}: sent {len(batch)} jobs, got skills for {got}"
                       + ("" if got == len(batch) else "  <-- some failed; they will be retried on the next run"))
            failed_in_a_row = failed_in_a_row + 1 if (batch and got == 0) else 0
            if failed_in_a_row >= 2:
                raise FatalError("2 batches in a row returned nothing, so something is systematically wrong "
                                 "(model name, key, or reply format). Re-run with --debug and check the "
                                 "[WARN] lines / debug log above.")

            # Jobs the model skipped are NOT saved, so the next run retries them.
            for jid, (row, has_text) in meta.items():
                if has_text and jid not in extracted:
                    continue
                # No description: no skills, and the yes/no answers are filled in by add_missing_flags.
                sk = extracted.get(jid) or {"hard_skills": [], "soft_skills": [],
                                            "certifications_or_licenses": [],
                                            "experience_level": None, "education": None,
                                            **{field: None for field in JOB_FLAG_COLUMNS}}
                rec = {"job_id": to_py(row[COL_ID]),
                       RENAME.get(COL_TITLE, COL_TITLE): to_py(row.get(COL_TITLE))}
                if a.source_label:
                    rec["source"] = a.source_label
                for c in company_cols + job_cols:       # company info first, then job info
                    rec[RENAME.get(c, c)] = to_py(row.get(c))
                for c in SKILL_COLS:
                    rec[c] = sk[c]
                for field, col in JOB_FLAG_COLUMNS.items():
                    rec[col] = sk[field]
                results.append(normalize_record(rec))

            save_outputs(results)

        add_missing_flags(pool, throttle, results, source_rows)

    except (AllKeysExhausted, FatalError) as e:
        save_outputs(results)
        print(f"\n[STOP] {e}")
        if results:
            print(f"Progress saved ({len(results)} jobs) in {OUTPUT_JSON}. "
                  f"Fix the issue (or add fresh keys to {a.keys}) and re-run to resume.")
        else:
            print("Nothing was extracted, so no output files were written.")
        sys.exit(1)

    if not results:
        print("\n[FAILED] No jobs were extracted, so no output files were written. See the [WARN] lines above.")
        sys.exit(1)
    save_outputs(results)
    no_skills = sum(1 for r in results if not r["hard_skills"] and not r["soft_skills"])
    print(f"\nDone! {len(results)} of {total} jobs saved to:\n  -> {OUTPUT_CSV}\n  -> {OUTPUT_JSON}")
    if len(results) < total:
        print(f"{total - len(results)} job(s) failed and were not saved. Re-run the same command to retry them.")
    if no_skills:
        print(f"Warning: {no_skills} saved job(s) have no skills at all (empty description or model returned nothing).")
        print("Re-run with --debug to see the raw model replies.")


if __name__ == "__main__":
    main()
