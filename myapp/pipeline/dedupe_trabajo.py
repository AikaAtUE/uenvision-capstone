"""
Trabajo duplicate-posting merge (Trabajo only; Kalibrr rows never come through here).

Trabajo lists the same ad once per city and again under a second source feed, each
copy with its own job_id and URL, so a job_id check misses them. Two passes, both
only ever merge postings from the same company:

  1. exact:  same company and the same description once lowercased and stripped of
             punctuation / spacing.
  2. near:   same company and descriptions that share >= NEAR_THRESHOLD of their
             5-word sequences (Jaccard), e.g. a repost with a reworded title.

From each group the earliest-posted row is kept. It gets three extra columns:
duplicate_count (how many copies were merged into it), other_locations (the copies'
cities) and merged_job_ids (their job_ids, so the extractor can drop skills it had
already extracted for them). Rows without a description are passed through untouched.

Stdlib only: compile_jobs_to_csv.py (a standalone script) and manager.py both use it.
"""
import html
import re
from datetime import datetime

NEAR_THRESHOLD = 0.8
SHINGLE_WORDS = 5
EXTRA_COLUMNS = ["duplicate_count", "other_locations", "merged_job_ids"]

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_COMPANY_SUFFIX_RE = re.compile(
    r"\b(inc|llc|ltd|limited|corp|corporation|co|gmbh|opc|philippines|phils|ph|the)\b")


def _norm(text) -> str:
    return _NON_ALNUM_RE.sub(" ", html.unescape(str(text or "")).lower()).strip()


def company_key(name) -> str:
    """'ATOS Information Technology Inc.' and 'Atos Information Technology' -> same key."""
    return " ".join(_COMPANY_SUFFIX_RE.sub(" ", _norm(name)).split())


def _shingles(words: list) -> set:
    if len(words) <= SHINGLE_WORDS:
        return {" ".join(words)}
    return {" ".join(words[i:i + SHINGLE_WORDS]) for i in range(len(words) - SHINGLE_WORDS + 1)}


def _posted_sort_key(row: dict, order: int):
    try:
        ts = datetime.fromisoformat(str(row.get("date_posted") or "")).timestamp()
    except ValueError:
        ts = float("inf")      # undated copies lose to dated ones
    return (ts, order)


def _location(row: dict) -> str:
    return str(row.get("city") or row.get("location_raw") or "").strip()


def dedupe_rows(rows: list, near_threshold: float = NEAR_THRESHOLD) -> tuple[list, dict]:
    """Returns (kept_rows in their original order, stats). Input rows are not modified."""
    n = len(rows)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    by_company: dict[str, list[int]] = {}
    desc_words: dict[int, list] = {}
    for i, row in enumerate(rows):
        words = _norm(row.get("description")).split()
        if not words:
            continue
        desc_words[i] = words
        by_company.setdefault(company_key(row.get("company_name")), []).append(i)

    # Pass 1: exact description within a company.
    exact_merges = 0
    for idxs in by_company.values():
        first_by_desc: dict[str, int] = {}
        for i in idxs:
            key = " ".join(desc_words[i])
            if key in first_by_desc:
                union(first_by_desc[key], i)
                exact_merges += 1
            else:
                first_by_desc[key] = i

    # Pass 2: near-identical description within a company (one representative per exact group).
    near_merges = 0
    if near_threshold < 1:
        for idxs in by_company.values():
            reps = [i for i in idxs if find(i) == i]
            if len(reps) < 2:
                continue
            sh = {i: _shingles(desc_words[i]) for i in reps}
            for a in range(len(reps)):
                for b in range(a + 1, len(reps)):
                    i, j = reps[a], reps[b]
                    if find(i) == find(j):
                        continue
                    si, sj = sh[i], sh[j]
                    if len(si & sj) / len(si | sj) >= near_threshold:
                        union(i, j)
                        near_merges += 1

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    keep: dict[int, dict] = {}
    for members in groups.values():
        members.sort(key=lambda i: _posted_sort_key(rows[i], i))
        best, others = members[0], members[1:]
        row = dict(rows[best])
        # A row that was already a merge result (re-imported CSV) brings its earlier merges along.
        ids, locs = [], []
        for i in members:
            if i != best:
                ids.append(str(rows[i].get("job_id") or "").strip())
            ids += _split(rows[i].get("merged_job_ids"))
            if i != best:
                locs.append(_location(rows[i]))
            locs += _split(rows[i].get("other_locations"))
        own = _location(row).lower()
        ids = [x for x in dict.fromkeys(ids) if x]
        seen_locs, uniq_locs = {own}, []
        for loc in locs:
            if loc and loc.lower() not in seen_locs:
                seen_locs.add(loc.lower())
                uniq_locs.append(loc)
        row["duplicate_count"] = len(ids)
        row["other_locations"] = "; ".join(uniq_locs)
        row["merged_job_ids"] = "; ".join(ids)
        keep[best] = row

    kept = [keep[i] for i in sorted(keep)]
    stats = {"input": n, "kept": len(kept), "removed": n - len(kept),
             "exact": exact_merges, "near": near_merges}
    return kept, stats


def _split(value) -> list:
    if not isinstance(value, str):      # blank cells arrive as NaN from pandas
        return []
    return [x.strip() for x in value.split(";") if x.strip()]


def merged_job_ids(rows) -> set:
    """All job_ids recorded as merged-away duplicates in a deduplicated Trabajo CSV."""
    return {jid for row in rows for jid in _split(row.get("merged_job_ids"))}
