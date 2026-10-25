"""
UEnvision — maps curriculum subjects to suggested skills from the real MIND
Tech Skills Ontology (data/ontology/mind_tech_ontology.csv), so the Student /
Alumni / Professor surveys can show "here's what's usually taught in this
subject — pick what applies" instead of a blank text box.

This is a plain keyword/heuristic matcher over the ontology's own columns
(name, synonyms, technicalDomains, solvesApplicationTasks, type,
concept_category) — not a trained model. It's meant to pre-populate
sensible suggestions; respondents can always add a skill that isn't
suggested (see the "Add another skill" row on each survey page).
"""
import csv
import re
import threading
from functools import lru_cache

from django.conf import settings

_LOCK = threading.Lock()
_ROWS_CACHE = None

STOPWORDS = {
    "and", "of", "the", "to", "in", "for", "with", "on", "a", "an", "or",
    "1", "2", "3", "i", "ii", "iii", "iv", "v",
    "introduction", "fundamentals", "principles", "concepts", "systems",
    "technologies", "technology", "project", "elective", "practicum",
    "computer", "computing", "science", "studies", "theory", "structures",
    "capstone", "thesis",
}

# keyword -> list of (field, value-substring, weight) boosts, applied on top of
# plain text matches against the ontology row's own name/synonyms.
DOMAIN_HINTS = {
    "database": [("type", "database", 4), ("technicalDomains", "data engineering", 3), ("technicalDomains", "data science", 2)],
    "network": [("technicalDomains", "networking", 5)],
    "networking": [("technicalDomains", "networking", 5)],
    "web": [("technicalDomains", "frontend", 3), ("technicalDomains", "backend", 2), ("technicalDomains", "fullstack", 2)],
    "mobile": [("technicalDomains", "mobile", 5)],
    "security": [("technicalDomains", "cybersecurity", 5)],
    "assurance": [("technicalDomains", "cybersecurity", 4)],
    "artificial": [("technicalDomains", "ml/ai", 5)],
    "intelligence": [("technicalDomains", "ml/ai", 4)],
    "machine": [("technicalDomains", "ml/ai", 4)],
    "learning": [("technicalDomains", "ml/ai", 2)],
    "analytics": [("solvesApplicationTasks", "data analysis", 4), ("technicalDomains", "data science", 2)],
    "analysis": [("solvesApplicationTasks", "data analysis", 2)],
    "cloud": [("technicalDomains", "devops", 4)],
    "devops": [("technicalDomains", "devops", 5)],
    "integration": [("technicalDomains", "devops", 2), ("technicalDomains", "backend", 1)],
    "architecture": [("technicalDomains", "backend", 2)],
    "game": [("technicalDomains", "game development", 5)],
    "embedded": [("technicalDomains", "embedded systems", 5)],
    "iot": [("technicalDomains", "iot", 5)],
    "software": [("technicalDomains", "backend", 2), ("technicalDomains", "fullstack", 2)],
    "engineering": [("technicalDomains", "backend", 1)],
    "operating": [("technicalDomains", "systems programming", 4)],
    "programming": [("type", "programminglanguage", 3)],
    "object-oriented": [("type", "programminglanguage", 2)],
    "testing": [("technicalDomains", "qa/testing", 5)],
    "quality": [("technicalDomains", "qa/testing", 3)],
    "desktop": [("technicalDomains", "desktop", 5)],
    "interaction": [("technicalDomains", "frontend", 2)],
    "human": [("technicalDomains", "frontend", 1)],
    "platform": [("technicalDomains", "backend", 1), ("technicalDomains", "mobile", 1)],
    "management": [("technicalDomains", "data engineering", 1)],
    "blockchain": [("technicalDomains", "blockchain", 5)],
    "automation": [("technicalDomains", "rpa", 3), ("technicalDomains", "devops", 2)],
}

_TEXT_FIELDS = [
    "name", "synonyms", "type", "technicalDomains", "solvesApplicationTasks", "concept_category",
]


def _tokenize(text):
    words = re.findall(r"[a-zA-Z][a-zA-Z\-]*", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def _ontology_path():
    return settings.DATA_DIR / "ontology" / "mind_tech_ontology.csv"


def _load_rows():
    global _ROWS_CACHE
    if _ROWS_CACHE is not None:
        return _ROWS_CACHE
    with _LOCK:
        if _ROWS_CACHE is not None:
            return _ROWS_CACHE
        rows = []
        path = _ontology_path()
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    lowered = {field: (row.get(field) or "").lower() for field in _TEXT_FIELDS}
                    rows.append({
                        "name": (row.get("name") or "").strip(),
                        "record_kind": row.get("record_kind") or "",
                        "_l": lowered,
                    })
        except OSError:
            rows = []
        _ROWS_CACHE = rows
        return rows


def _specificity(row):
    """How narrowly tagged a row is (fewer technicalDomains = more specific).
    Used as a tiebreak so a general-purpose, every-domain-tagged language
    doesn't drown out tools that are actually specific to the subject —
    e.g. Java/Python are tagged under nearly every domain including
    Cybersecurity, so without this a security subject would surface "Java"
    ahead of actual security tools."""
    raw = row["_l"].get("technicalDomains", "")
    if not raw:
        return 99
    return len([d for d in raw.split("|") if d.strip()])


def suggest_skills_for_subject(subject_name, limit=12):
    rows = _load_rows()
    if not rows:
        return []
    tokens = _tokenize(subject_name)
    if not tokens:
        return []

    scored = {}  # name -> (score, specificity, is_skill)
    for row in rows:
        name = row["name"]
        if not name:
            continue
        score = 0
        hint_hit = False
        for tok in tokens:
            hints = DOMAIN_HINTS.get(tok)
            if hints:
                for field, value, weight in hints:
                    if value in row["_l"].get(field, ""):
                        score += weight
                        hint_hit = True
            else:
                # Only fall back to plain substring matching for words that
                # aren't already covered by a domain hint, to avoid short
                # common words (web, data, security, ...) flooding matches
                # via raw substring hits inside unrelated tool names.
                if tok in row["_l"]["name"]:
                    score += 4
                    hint_hit = True
                if tok in row["_l"]["synonyms"]:
                    score += 3
                    hint_hit = True
        if not hint_hit or score <= 0:
            continue
        specificity = _specificity(row)
        is_skill = row["record_kind"] == "Skill"
        prev = scored.get(name)
        candidate = (score, specificity, is_skill)
        if prev is None or (candidate[0], -candidate[1], candidate[2]) > (prev[0], -prev[1], prev[2]):
            scored[name] = candidate

    ranked = sorted(
        scored.items(),
        key=lambda kv: (kv[1][0], -kv[1][1], kv[1][2]),
        reverse=True,
    )
    return [name for name, _ in ranked[:limit]]


@lru_cache(maxsize=1)
def subject_skill_map():
    """{"CODE": [suggested skill names]} for every subject in the
    curriculum catalog. Uses the hand-curated lists in subject_skills.py; the
    keyword heuristic above (suggest_skills_for_subject) gave suggestions that
    were too far from the subjects, so it's no longer used for the surveys.
    Subjects without a curated list (Professional Electives) get none."""
    from . import curriculum_data, skills_catalog

    skills_catalog.ensure_curated()
    out = {}
    for code, info in curriculum_data.subject_by_code().items():
        out[code] = skills_catalog.suggestions_for(info["name"])
    return out
