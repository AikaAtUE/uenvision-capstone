"""
Skill standardization core (no Gemini, no Django): exact lookup + fuzzy candidates.

Files (all under data/ontology/):
    mind_tech_ontology.csv   the ontology you provided. Never edited.
    custom_skills.csv        skills that were not in the ontology; grows by itself, same columns as
                             the ontology plus status / first_seen / times_seen. Safe to edit by hand.
    skill_mapping.csv        remembered decisions "raw wording -> standard name", so each wording is
                             only ever judged once.

Used by standardize_skills_gemini.py (run as a script).
"""
import csv
import os
import re
import tempfile
from collections import defaultdict
from datetime import date
from pathlib import Path

try:
    from rapidfuzz import fuzz, process
    HAVE_RAPIDFUZZ = True
except ImportError:          # slower, slightly different scores, same idea
    import difflib
    HAVE_RAPIDFUZZ = False

MIN_SCORE = 60          # fuzzy candidates scoring lower are dropped
TOP_K = 5
MIN_FUZZY_LEN = 4       # "R", "C", "Go": exact match only

CUSTOM_COLUMNS = ["record_kind", "name", "synonyms", "type", "status", "first_seen", "times_seen"]
MAPPING_COLUMNS = ["raw", "standard", "method", "decided"]

_VERSION = re.compile(r"\bv?\d+(\.\d+)+\b")     # "python 3.11" -> "python"


def norm(text: str) -> str:
    """Lowercase; keep + and # (C++, C#); everything else becomes one space; drop dotted versions."""
    t = _VERSION.sub(" ", str(text).lower().replace("&", " and "))
    return re.sub(r"[^a-z0-9+#]+", " ", t).strip()


def clean_display(text: str) -> str:
    return " ".join(str(text).split())


class SkillIndex:
    def __init__(self):
        self.term_to_names = defaultdict(set)   # normalized term -> {standard names}
        self.terms = []                         # normalized terms (fuzzy search space)
        self.owner = []                         # terms[i] belongs to owner[i]
        self.names = set()

    def add(self, name: str, synonyms: str = ""):
        name = clean_display(name)
        if not name:
            return
        self.names.add(name)
        for t in [name] + str(synonyms or "").split("|"):
            n = norm(t)
            if n and name not in self.term_to_names[n]:
                self.term_to_names[n].add(name)
                self.terms.append(n)
                self.owner.append(name)

    def exact(self, skill: str) -> list:
        """Standard names for this wording: [] unknown, [x] clean hit, [x, y, ...] ambiguous."""
        return sorted(self.term_to_names.get(norm(skill), []))

    def fuzzy(self, skill: str, exclude=()) -> list:
        """Up to TOP_K distinct (standard name, score, matched term). Suggestions only."""
        q = norm(skill)
        if len(q) < MIN_FUZZY_LEN or not self.terms:
            return []
        if HAVE_RAPIDFUZZ:
            # token_sort_ratio = whole-string similarity with word order ignored. Deliberately NOT
            # token_set / partial / WRatio: those call "excel" a perfect match for "Excel Power Pivot".
            found = process.extract(q, self.terms, scorer=fuzz.token_sort_ratio, limit=60, score_cutoff=MIN_SCORE)
            hits = [(self.terms[i], s, i) for _, s, i in found]
        else:
            hits = []
            sm = difflib.SequenceMatcher(None)
            sm.set_seq2(q)                               # q is compared against every term: cache its analysis
            cut = MIN_SCORE / 100
            for i, t in enumerate(self.terms):
                if abs(len(t) - len(q)) > max(len(q), len(t)) * 0.5:
                    continue
                sm.set_seq1(t)
                if sm.real_quick_ratio() < cut or sm.quick_ratio() < cut:    # cheap upper bounds first
                    continue
                s = sm.ratio() * 100
                if s >= MIN_SCORE:
                    hits.append((t, s, i))
            hits.sort(key=lambda h: -h[1])
        best = {}
        for term, score, i in hits:                      # several synonyms of one entry count once
            if self.owner[i] not in exclude:
                best.setdefault(self.owner[i], (round(score), term))
        return [(n, s, t) for n, (s, t) in list(best.items())[:TOP_K]]


# ------------------------------- files -------------------------------
def _read_rows(path):
    p = Path(path)
    if not p.is_file():
        return []
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_index(ontology_csv, custom_csv) -> SkillIndex:
    idx = SkillIndex()
    for path in (ontology_csv, custom_csv):              # ontology first, then the growing custom file
        for r in _read_rows(path):
            idx.add(r.get("name", ""), r.get("synonyms", ""))     # both "Skill" and "Concept" records
    return idx


def append_custom(custom_csv, name: str, synonyms, times_seen: int):
    p = Path(custom_csv)
    p.parent.mkdir(parents=True, exist_ok=True)
    new_file = not p.is_file() or p.stat().st_size == 0
    with open(p, "a", encoding="utf-8-sig" if new_file else "utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CUSTOM_COLUMNS, lineterminator="\r\n")
        if new_file:
            w.writeheader()
        w.writerow({"record_kind": "Skill", "name": name, "synonyms": " | ".join(synonyms), "type": "",
                    "status": "auto", "first_seen": date.today().isoformat(), "times_seen": times_seen})


def load_mapping(path) -> dict:
    return {norm(r["raw"]): r["standard"] for r in _read_rows(path) if r.get("raw") and r.get("standard")}


def append_mapping(path, raw: str, standard: str, method: str):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    new_file = not p.is_file() or p.stat().st_size == 0
    with open(p, "a", encoding="utf-8-sig" if new_file else "utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MAPPING_COLUMNS, lineterminator="\r\n")
        if new_file:
            w.writeheader()
        w.writerow({"raw": raw, "standard": standard, "method": method, "decided": date.today().isoformat()})


def write_csv_atomic(path, fieldnames, rows):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\r\n", extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, p)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
