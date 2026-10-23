#!/usr/bin/env python3
"""
Standardize the hard skills in data/.state/extracted_skills.json (the extractor's resume file).

  1. exact lookup against the ontology + custom_skills.csv          (free, instant)
  2. remembered decisions in skill_mapping.csv                      (free, instant)
  3. everything else: fuzzy top-5 candidates -> a TEMPORARY CSV -> Gemini picks one or says none,
     N rows per prompt (same "rows per prompt" setting as extraction)
  4. "none" -> a new row in custom_skills.csv, so the next wording of it matches exactly
  5. extracted_skills.json / .csv and hard_skills.csv / soft_skills.csv are rewritten.
     The original wording is kept in the hard_skills_raw column.

Run:  python standardize_skills_gemini.py --json DIR/extracted_skills.json --output-dir DATA \
          --ontology-dir DATA/ontology --keys api_keys.txt --batch-size 20
"""
import argparse
import csv
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field
from google.genai import types

import extract_skills_gemini as ex
import skill_standardizer as ss

SYSTEM_PROMPT = (
    "You standardize technical skill names from job postings. For each row you get a skill exactly as a "
    "posting worded it, the job title, and up to 5 candidate standard names (numbered 1-5).\n"
    "- If one candidate is the SAME skill (same tool, language, library, service or concept - a different "
    "spelling, abbreviation, vendor prefix or word order), answer its number in `choice`.\n"
    "- Similar but different things are NOT the same: 'Excel' is not 'Excel Power Pivot', 'Java' is not "
    "'JavaScript', 'SQL Server' is not 'MySQL'.\n"
    "- If no candidate is the same skill, answer choice 0 and give `new_name`: the common, properly "
    "capitalised name of the skill (e.g. 'Microsoft Excel', 'Agile', 'Linux'), no version numbers.\n"
    "- Never invent a candidate number. Keep `id` exactly as given."
)


class Verdict(BaseModel):
    id: int = Field(description="The row id exactly as given")
    choice: int = Field(description="Number 1-5 of the matching candidate, or 0 if none matches")
    new_name: Optional[str] = Field(description="Standard name to use when choice is 0, otherwise null")


class Verdicts(BaseModel):
    results: List[Verdict] = Field(description="Exactly one entry per row, in the same order")


TEMP_COLUMNS = ["id", "skill", "times_seen", "job_title"] + \
    [f"{k}_{i}" for i in range(1, ss.TOP_K + 1) for k in ("candidate", "score")]


def candidate_row(idx, item, row_id):
    cands = item["fixed"] or [c[0] for c in idx.fuzzy(item["skill"])]
    scores = {c[0]: c[1] for c in idx.fuzzy(item["skill"])}
    row = {"id": row_id, "skill": item["skill"], "times_seen": item["n"], "job_title": item["title"]}
    for i in range(ss.TOP_K):
        name = cands[i] if i < len(cands) else ""
        row[f"candidate_{i + 1}"] = name
        row[f"score_{i + 1}"] = scores.get(name, "") if name else ""
    return row


def ask_gemini(pool, throttle, rows, model, max_tokens):
    """rows (dicts read back from the temp CSV) -> {id: (choice, new_name)}. Same key-rotation / retry
    rules as the extractor."""
    payload = [{"id": int(r["id"]), "skill": r["skill"], "job_title": r["job_title"],
                "candidates": {i: r[f"candidate_{i}"] for i in range(1, ss.TOP_K + 1) if r[f"candidate_{i}"]}}
               for r in rows]
    prompt = "Standardize these skills:\n" + json.dumps(payload, ensure_ascii=False, indent=1)
    retries = 0
    while True:
        throttle.wait()
        try:
            resp = pool.client.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT, response_mime_type="application/json",
                    response_schema=Verdicts, max_output_tokens=max_tokens))
            parsed = getattr(resp, "parsed", None)
            if parsed is None:
                txt = re.sub(r"^```(?:json)?|```$", "", (resp.text or "").strip(), flags=re.M).strip()
                parsed = Verdicts.model_validate_json(txt)
            if not parsed.results:
                raise ValueError("model returned zero results")
            return {v.id: (v.choice, v.new_name) for v in parsed.results}
        except Exception as e:
            kind = ex.classify_error(e)
            if kind == "fatal":
                raise ex.FatalError(f"{type(e).__name__}: {str(e)[:500]}")
            if kind == "rotate":
                print(f"[KEY] {pool.label} unusable (quota/invalid): {str(e)[:120]}")
                if not pool.next_key():
                    raise ex.AllKeysExhausted("All API keys in the keys file are exhausted/invalid.")
                retries = 0
                continue
            retries += 1
            if retries > ex.MAX_RETRIES:
                if kind == "wait" and pool.next_key():
                    retries = 0
                    continue
                if kind == "wait":
                    raise ex.AllKeysExhausted("All API keys are rate limited / exhausted.")
                print(f"[WARN] Standardizing {len(rows)} rows failed after retries: {str(e)[:200]}")
                return None
            wait = ex.retry_delay(e) if kind == "wait" else 5 * 2 ** (retries - 1)
            print(f"[WARN] {type(e).__name__}: {str(e)[:200]} -> retry {retries} in {wait:.0f}s")
            time.sleep(wait)


def dedupe(items):
    seen, out = set(), []
    for x in items:
        k = ss.norm(x)
        if k and k not in seen:
            seen.add(k)
            out.append(x)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True, help="extracted_skills.json (resume file)")
    ap.add_argument("--output-dir", required=True, help="folder for extracted_skills.csv / hard_skills.csv ...")
    ap.add_argument("--output", default="extracted_skills")
    ap.add_argument("--ontology-dir", required=True)
    ap.add_argument("--ontology-file", default="mind_tech_ontology.csv")
    ap.add_argument("--temp-csv", required=True, help="temporary CSV that is sent to Gemini")
    ap.add_argument("--keys", required=True)
    ap.add_argument("--model", default=ex.MODEL)
    ap.add_argument("--batch-size", type=int, default=ex.BATCH_SIZE)
    ap.add_argument("--rpm", type=float, default=ex.RPM)
    a = ap.parse_args()

    batch_size = max(1, min(a.batch_size, ex.MAX_BATCH_SIZE))
    onto = Path(a.ontology_dir) / a.ontology_file
    custom = Path(a.ontology_dir) / "custom_skills.csv"
    mapping_path = Path(a.ontology_dir) / "skill_mapping.csv"
    if not onto.is_file():
        raise SystemExit(f"ERROR: ontology file not found: {onto}")
    if not Path(a.json).is_file():
        raise SystemExit("ERROR: there are no extracted skills yet. Run Extract Skills first.")

    ex.OUTPUT_CSV = os.path.join(a.output_dir, a.output + ".csv")
    ex.OUTPUT_JSON = a.json
    ex.MODEL = a.model

    results = [ex.normalize_record(r) for r in json.loads(Path(a.json).read_text(encoding="utf-8"))]
    idx = ss.load_index(onto, custom)
    mapping = ss.load_mapping(mapping_path)
    print(f"Ontology: {len(idx.names):,} skills, {len(idx.terms):,} searchable terms "
          f"(fuzzy matcher: {'rapidfuzz' if ss.HAVE_RAPIDFUZZ else 'difflib fallback - pip install rapidfuzz'})")

    # Always start from the original wording, so re-running after the custom file grew gives the same result.
    raw_of = lambda r: list(r.get("hard_skills_raw") or r.get("hard_skills") or [])
    wanted = {}          # normalized wording -> {"skill", "n", "title"}
    for r in results:
        for s in raw_of(r):
            k = ss.norm(s)
            if not k:
                continue
            w = wanted.setdefault(k, {"skill": ss.clean_display(s), "n": 0, "title": r.get("job_name") or ""})
            w["n"] += 1
    print(f"{len(wanted):,} different hard-skill wordings in {len(results)} postings")

    resolved, pending = {}, []
    counts = Counter()
    for k, w in sorted(wanted.items(), key=lambda kv: -kv[1]["n"]):        # most frequent first
        hit = idx.exact(w["skill"])
        if len(hit) == 1:
            resolved[k] = hit[0]; counts["exact"] += 1
        elif k in mapping:
            resolved[k] = mapping[k]; counts["remembered"] += 1
        else:                                  # unknown, or ambiguous (several entries share the wording)
            pending.append({**w, "k": k, "fixed": hit})
    print(f"Exact match: {counts['exact']:,} | remembered earlier: {counts['remembered']:,} | "
          f"need a closer look: {len(pending):,}")

    failed = None
    if pending:
        temp = Path(a.temp_csv)
        rows = [candidate_row(idx, p, i + 1) for i, p in enumerate(pending)]
        ss.write_csv_atomic(temp, TEMP_COLUMNS, rows)
        print(f"Temporary file with candidates: {temp}  ({len(rows)} rows, {batch_size} rows per prompt)")
        pool = ex.KeyPool(a.keys)
        throttle = ex.Throttle(a.rpm)
        print(f"Loaded {len(pool.keys)} API key(s). Using {pool.label}. Model: {a.model}")
        n_batches = (len(pending) + batch_size - 1) // batch_size
        try:
            for b in range(n_batches):
                lo, hi = b * batch_size, (b + 1) * batch_size
                for i in range(lo, min(hi, len(pending))):       # entries added by earlier batches count as candidates
                    rows[i] = candidate_row(idx, pending[i], i + 1)
                ss.write_csv_atomic(temp, TEMP_COLUMNS, rows)
                with open(temp, encoding="utf-8-sig", newline="") as f:     # what Gemini gets = what's in the file
                    chunk = list(csv.DictReader(f))[lo:hi]
                verdicts = ask_gemini(pool, throttle, chunk, a.model, ex.MAX_OUTPUT_TOKENS)
                if verdicts is None:
                    print(f"Batch {b + 1}/{n_batches}: no usable answer; those skills stay as written and will be retried next run")
                    continue
                done = 0
                for row in chunk:
                    p = pending[int(row["id"]) - 1]
                    choice, new_name = verdicts.get(int(row["id"]), (None, None))
                    names = [row[f"candidate_{i}"] for i in range(1, ss.TOP_K + 1)]
                    if choice is None:
                        continue
                    if 1 <= choice <= ss.TOP_K and names[choice - 1]:
                        std, how = names[choice - 1], "judge-picked"
                    else:
                        std = ss.clean_display(new_name or "") or p["skill"]
                        known = idx.exact(std)
                        if len(known) == 1:                      # Gemini's name already exists
                            std, how = known[0], "judge-existing"
                        else:
                            syn = sorted({p["skill"].lower(), std.lower()})
                            ss.append_custom(custom, std, syn, p["n"])
                            idx.add(std, " | ".join(syn))
                            how = "new-custom"
                            print(f"  + new custom skill: {std}  (from \"{p['skill']}\", seen {p['n']}x)")
                    resolved[p["k"]] = std
                    ss.append_mapping(mapping_path, p["skill"], std, how)
                    counts[how] += 1
                    done += 1
                print(f"Batch {b + 1}/{n_batches}: {done} of {len(chunk)} skills standardized")
        except (ex.AllKeysExhausted, ex.FatalError) as e:
            failed = e
            print(f"\n[STOP] {e}\nWhat was decided so far is saved; run again to continue.")

    # ---- apply to every posting ----
    for r in results:
        raw = raw_of(r)
        if not raw:
            continue
        r["hard_skills_raw"] = raw
        r["hard_skills"] = dedupe([resolved.get(ss.norm(s), ss.clean_display(s)) for s in raw if ss.norm(s)])
    ex.save_outputs(results)
    left = sum(1 for k in wanted if k not in resolved)
    print(f"\nDone. exact {counts['exact']:,}, remembered {counts['remembered']:,}, picked from candidates "
          f"{counts['judge-picked'] + counts['judge-existing']:,}, new custom skills {counts['new-custom']:,}"
          + (f", {left:,} left as written (will retry next run)" if left else ""))
    print(f"Rewrote {ex.OUTPUT_CSV} (original wording kept in hard_skills_raw)")
    if not failed and Path(a.temp_csv).is_file():
        Path(a.temp_csv).unlink()          # the temporary file is only kept when the run didn't finish
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
