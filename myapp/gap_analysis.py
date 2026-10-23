"""
UEnvision — Gap analysis: compares industry-demanded skills (from the job-scraping
pipeline's data/extracted_skills.csv) against academically-covered skills (from the
Student / Fresh Grad Alumni / Professor curriculum surveys, CurriculumSurveyResponse).

Scope, deliberately kept narrow for this first pass:

* Industry side only ever looks at HARD skills (`hard_skills` column), not soft
  skills — a curriculum subject most directly "teaches" hard/technical skills, and
  mixing in soft skills (communication, teamwork, ...) would make the alignment
  number harder to defend. The existing hard/soft toggle on the Dashboard's other
  two tabs doesn't apply here.

* Academic side only counts skills tagged as TAUGHT/LEARNED per subject
  (subjects[].skills[]) plus an alumni's "overall skills learned" picker — not the
  alumni employment-branch fields (skills_applied / skills_to_learn / upskilling_skills).
  Those are an alumni's own after-the-fact opinion about what they wish they'd
  learned, which is a different (and interesting, but separate) signal from "what
  was actually covered in a subject" — mixing them in would conflate the two.

* Skill-name standardization uses only EXACT (normalized) matches against the MIND
  Tech Skills Ontology, via the same SkillIndex already used by the scrape/extract
  pipeline (skill_standardizer.py) — never fuzzy matching. Fuzzy matching was tested
  against the real 228-posting dataset and found unreliable even at high scores
  (e.g. "Scrum" -> "Customer Relationship Management" at 75, "Change Management" ->
  "Multi-channel Management" at 91) — good enough to *suggest*, not good enough to
  silently merge two different skills into one gap number. A skill with no exact
  ontology match is still counted (under its own cleaned wording, normalized so
  "SQL" / "sql" / "  SQL " all collapse together) rather than dropped, so totals
  stay accurate; it just won't line up with a differently-worded academic mention.
  Running the real Gemini-based standardizer (standardize_skills_gemini.py) over
  the industry data first would improve this — that's a separate, API-quota-spending
  step, so it's not done automatically here.
"""
import math

from django.conf import settings

from .models import CurriculumSurveyResponse
from .pipeline import manager as pipeline
from .pipeline.skill_standardizer import SkillIndex, clean_display, load_index, norm
from .pipeline.skills_schema import split_skills

MAX_LISTED = 12  # how many under-taught / well-covered skills the UI shows


def _ontology_dir():
    return settings.DATA_DIR / "ontology"


_INDEX_CACHE = None


def _ontology_index() -> SkillIndex:
    """Loaded once per process, same pattern as ontology.py's own cache. The
    ontology file never changes at runtime, and custom_skills.csv only grows via
    the (separate) Gemini standardization step, not from anything in this module."""
    global _INDEX_CACHE
    if _INDEX_CACHE is None:
        d = _ontology_dir()
        _INDEX_CACHE = load_index(d / "mind_tech_ontology.csv", d / "custom_skills.csv")
    return _INDEX_CACHE


def _standardize(raw: str, index: SkillIndex):
    """-> (group_key, display_name) or None for a blank skill.
    group_key is what mentions are tallied under: the ontology's own standard name
    when there's exactly one unambiguous exact match, otherwise the mention's own
    normalized wording (so near-duplicates like "React.js" / "react js" still
    collapse together even without an ontology hit)."""
    display = clean_display(raw)
    if not display:
        return None
    hits = index.exact(display)
    if len(hits) == 1:
        display = hits[0]
    key = norm(display) or display.lower()
    return key, display


def _tally(mention_sets):
    """mention_sets: iterable of {key: display} dicts, one per "unit" (job posting
    or survey response) — a skill is counted once per unit even if mentioned twice.
    -> (counts, label) where label[key] is the most common display spelling."""
    counts, forms = {}, {}
    for sk in mention_sets:
        for k, disp in sk.items():
            counts[k] = counts.get(k, 0) + 1
            forms.setdefault(k, {}).setdefault(disp, 0)
            forms[k][disp] += 1
    label = {k: max(f.items(), key=lambda kv: (kv[1], kv[0]))[0] for k, f in forms.items()}
    return counts, label


# ---------------------------------------------------------------------------
# Industry side
# ---------------------------------------------------------------------------
def _industry_mentions(source: str = "", level: str = ""):
    """-> (list of {key: display} per matching job posting, info dict)."""
    loaded = pipeline.load_table("extracted")
    if loaded is None:
        return [], {"exists": False}
    columns, rows = loaded
    idx = {c: i for i, c in enumerate(columns)}

    def get(r, c):
        i = idx.get(c)
        return r[i].strip() if i is not None and i < len(r) else ""

    chosen = [r for r in rows
              if (not source or get(r, "source") == source)
              and (not level or (get(r, "experience_level") or "Not specified") == level)]

    index = _ontology_index()
    jobs = []
    for r in chosen:
        skills = {}
        for raw in split_skills(get(r, "hard_skills")):
            hit = _standardize(raw, index)
            if hit:
                skills.setdefault(hit[0], hit[1])
        jobs.append(skills)
    return jobs, {"exists": True, "total_rows": len(rows), "matched_rows": len(chosen)}


# ---------------------------------------------------------------------------
# Academic side
# ---------------------------------------------------------------------------
def _skill_names_from(entries):
    for sk in entries or []:
        if isinstance(sk, dict):
            name = sk.get("name")
        else:
            name = sk
        if name and str(name).strip():
            yield str(name)


def _academic_mentions():
    """-> (list of {key: display} per survey response that named at least one
    taught/learned skill, counts-by-respondent-type dict)."""
    index = _ontology_index()
    rows = []
    by_type = {"student": 0, "alumni": 0, "professor": 0}
    for respondent_type, data in CurriculumSurveyResponse.objects.all().values_list("respondent_type", "data"):
        if not isinstance(data, dict):
            continue
        names = set()
        for subj in data.get("subjects") or []:
            if isinstance(subj, dict):
                names.update(_skill_names_from(subj.get("skills")))
        names.update(_skill_names_from(data.get("overall_skills")))  # alumni-only field; no-op otherwise
        if not names:
            continue
        skills = {}
        for raw in names:
            hit = _standardize(raw, index)
            if hit:
                skills.setdefault(hit[0], hit[1])
        if skills:
            rows.append(skills)
            if respondent_type in by_type:
                by_type[respondent_type] += 1
    return rows, by_type


# ---------------------------------------------------------------------------
# Put it together
# ---------------------------------------------------------------------------
def compute(top: int = 10, source: str = "", level: str = "") -> dict:
    """Numbers behind the Dashboard's "Alignment score" / "High-priority skill
    gaps" stat cards and the Skill Gap Analysis tab. `top` / `source` / `level`
    match the same controls already used for the Top-in-demand-skills tab, so the
    two stay in sync — this always looks at hard skills only (see module docstring)."""
    top = max(1, min(int(top), 30))
    industry_jobs, info = _industry_mentions(source, level)
    if not info["exists"]:
        return {"exists": False}

    industry_counts, industry_label = _tally(industry_jobs)
    total_postings = len(industry_jobs)
    industry_ranked = sorted(industry_counts.items(), key=lambda kv: (-kv[1], industry_label[kv[0]].lower()))
    top_n = industry_ranked[:top]

    academic_rows, by_type = _academic_mentions()
    academic_counts, academic_label = _tally(academic_rows)
    total_responses = len(academic_rows)
    has_survey_data = total_responses > 0

    industry_vec = [c for _, c in top_n]
    academic_vec = [academic_counts.get(k, 0) for k, _ in top_n]
    dot = sum(a * b for a, b in zip(industry_vec, academic_vec))
    mag_i = math.sqrt(sum(a * a for a in industry_vec))
    mag_a = math.sqrt(sum(a * a for a in academic_vec))
    cosine = (dot / (mag_i * mag_a)) if (mag_i and mag_a) else 0.0

    rows = []
    for k, c in top_n:
        academic_c = academic_counts.get(k, 0)
        industry_pct = round(c / total_postings * 100, 1) if total_postings else 0.0
        academic_pct = round(academic_c / total_responses * 100, 1) if total_responses else 0.0
        rows.append({
            "skill": industry_label[k],
            "industry_count": c,
            "industry_pct": industry_pct,
            "academic_count": academic_c,
            "academic_pct": academic_pct,
            "gap_score": round(industry_pct - academic_pct, 1),
        })

    under_taught = sorted(
        (r for r in rows if r["gap_score"] > 0),
        key=lambda r: (-r["gap_score"], -r["industry_count"]),
    )[:MAX_LISTED]
    well_covered = sorted(
        (r for r in rows if r["academic_count"] > 0),
        key=lambda r: (-r["academic_count"], -r["industry_count"]),
    )[:MAX_LISTED]

    return {
        "exists": True,
        "has_survey_data": has_survey_data,
        "survey_responses": total_responses,
        "survey_responses_by_type": by_type,
        "postings_considered": total_postings,
        "alignment_score": round(cosine * 100, 1),
        "alignment_cosine": round(cosine, 3),
        "under_taught": under_taught,
        "well_covered": well_covered,
        "top_gap": under_taught[0]["skill"] if under_taught else None,
    }
