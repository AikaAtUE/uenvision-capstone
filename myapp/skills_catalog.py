"""
UEnvision — the searchable skill catalog behind the survey skill pickers:
MIND Tech Skills Ontology (data/ontology/mind_tech_ontology.csv, never edited)
plus data/ontology/custom_skills.csv, which grows with

* "curated" rows: suggestions from subject_skills.py that the ontology lacks, and
* "user_added" rows: skills a survey respondent searched for, didn't find, and added.

Both files use the same columns the scrape/extract standardizer already reads
(pipeline/skill_standardizer.py), so new skills line up in the gap analysis too.
"""
import re
import threading

from django.conf import settings

from .pipeline.skill_standardizer import _read_rows, append_custom, clean_display, load_index, norm
from .subject_skills import SUBJECT_SKILLS

MAX_SKILL_LENGTH = 60
_ALLOWED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 +#./&()'’-]*$")
_LOCK = threading.Lock()
_ENTRIES = None          # [(display name, normalized name, (normalized synonyms, ...), source, {normalized synonym: as written})]
_CURATED_DONE = False


def ontology_csv():
    return settings.DATA_DIR / "ontology" / "mind_tech_ontology.csv"


def custom_csv():
    return settings.DATA_DIR / "ontology" / "custom_skills.csv"


def _invalidate():
    global _ENTRIES
    _ENTRIES = None
    from . import gap_analysis   # its exact-match index includes custom_skills.csv as well
    gap_analysis._INDEX_CACHE = None


def _entries():
    global _ENTRIES
    if _ENTRIES is None:
        seen, out = set(), []
        for path, source in ((ontology_csv(), "ontology"), (custom_csv(), "custom")):
            for r in _read_rows(path):
                name = clean_display(r.get("name", ""))
                key = norm(name)
                if not name or key in seen:
                    continue
                seen.add(key)
                written = {}
                for t in str(r.get("synonyms") or "").split("|"):
                    if t.strip() and norm(t) != key:
                        written.setdefault(norm(t), " ".join(t.split()))
                out.append((name, key, tuple(written), source, written))
        _ENTRIES = out
    return _ENTRIES


def ensure_curated():
    """Add every curated subject skill the ontology/custom file doesn't know yet
    to custom_skills.csv (status "curated"). Runs once per process."""
    global _CURATED_DONE
    if _CURATED_DONE:
        return
    with _LOCK:
        if _CURATED_DONE:
            return
        index = load_index(ontology_csv(), custom_csv())
        added = False
        for names in SUBJECT_SKILLS.values():
            for name in names:
                if not index.exact(name):
                    append_custom(custom_csv(), name, [], 0, status="curated")
                    index.add(name)
                    added = True
        if added:
            _invalidate()
        _CURATED_DONE = True


def suggestions_for(subject_name):
    return list(SUBJECT_SKILLS.get(subject_name, []))


def search(query, limit=10):
    """Best matches for what a respondent typed, synonyms included ("JS" finds
    JavaScript, "k8s" finds Kubernetes): exact name, exact synonym, name starting
    with it, synonym starting with it, a word in the name starting with it, then
    anywhere in a synonym or the name. A synonym hit says which synonym matched."""
    q = norm(query)
    if not q:
        return []
    ranked = []
    for name, key, syns, source, written in _entries():
        alias = None
        if key == q:
            rank = 0
        elif q in syns:
            rank, alias = 1, q
        elif key.startswith(q):
            rank = 2
        elif any(s.startswith(q) for s in syns):
            rank, alias = 3, next(s for s in syns if s.startswith(q))
        elif (" " + key).find(" " + q) >= 0:
            rank = 4
        elif len(q) >= 3 and any(q in s for s in syns):
            rank, alias = 5, next(s for s in syns if q in s)
        elif len(q) >= 3 and q in key:
            rank = 6
        else:
            continue
        ranked.append((rank, len(name), name.lower(), name, source, written.get(alias) if alias else None))
    ranked.sort()
    out = []
    for rank, _, _, name, source, alias in ranked[:limit]:
        item = {"name": name, "source": source, "exact": rank <= 1}
        if alias:
            item["synonym"] = alias
        out.append(item)
    return out


def validate_new_skill(raw):
    """-> (clean name, error or None)."""
    name = clean_display(raw or "")
    if not 2 <= len(name) <= MAX_SKILL_LENGTH:
        return name, f"A skill name must be 2 to {MAX_SKILL_LENGTH} characters."
    if not _ALLOWED.match(name):
        return name, "Use letters, numbers, spaces and + # . / & ( ) ' - only."
    return name, None


def add_custom_skill(raw):
    """-> (name, created, error). An existing skill with the same normalized name
    (or synonym) is returned instead of adding a duplicate."""
    name, error = validate_new_skill(raw)
    if error:
        return name, False, error
    with _LOCK:
        index = load_index(ontology_csv(), custom_csv())
        hits = index.exact(name)
        if hits:
            return hits[0], False, None
        append_custom(custom_csv(), name, [], 1, status="user_added")
        _invalidate()
    return name, True, None
