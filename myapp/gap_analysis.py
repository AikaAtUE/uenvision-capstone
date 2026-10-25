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

* Depth weighting. A survey mention isn't a yes/no any more: each skill carries the
  respondent's level, turned into a 0-1 weight (LEVEL_WEIGHTS). Professors rate HOW
  a skill is taught (Introduced 1/3, Practiced 2/3, Applied 1); students/alumni rate
  how proficient they ended up (Beginner .25 ... Expert 1). A response's weight for a
  skill is its highest level across that response's subjects, and
  academic_pct = sum of those weights / number of responses * 100, i.e. a
  "depth-weighted coverage" that equals the old plain mention rate when everyone
  answers at the top level. taught_depth (professors) and learned_proficiency
  (students + alumni) are also reported separately so the two views can be compared.

* Per-subject breakdown. Job postings never say which subject a skill belongs to, so
  the link from industry demand to a subject comes from the academic side: a skill
  is attributed to a subject when a respondent reported it for that subject, and an
  under-taught skill is proposed for a subject when the MIND ontology suggests it
  for that subject (ontology.subject_skill_map) but nobody reported it there.
"""
import math

from django.conf import settings

from .models import CurriculumSurveyResponse
from .pipeline import manager as pipeline
from .pipeline.skill_standardizer import SkillIndex, clean_display, load_index, norm
from .pipeline.skills_schema import split_skills

MAX_LISTED = 12  # how many under-taught / well-covered skills the UI shows
MAX_SUBJECT_SKILLS = 8  # per-subject lists in the breakdown

# Survey level -> weight in 0..1. An unknown or missing level counts in full, the
# same as the original unweighted mention count.
LEVEL_WEIGHTS = {
    # Professor survey: how the skill is taught
    "introduced": 1 / 3, "practiced": 2 / 3, "applied": 1.0,
    # Student / alumni surveys: proficiency after the subject
    "beginner": 0.25, "intermediate": 0.5, "advanced": 0.75, "expert": 1.0,
}
LEARNER_TYPES = ("student", "alumni")


def level_weight(level) -> float:
    return LEVEL_WEIGHTS.get(str(level or "").strip().lower(), 1.0)


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
def _skill_entries(entries):
    """-> (name, level) for each non-blank skill entry (dicts or bare names)."""
    for sk in entries or []:
        if isinstance(sk, dict):
            name, lvl = sk.get("name"), sk.get("level")
        else:
            name, lvl = sk, None
        if name and str(name).strip():
            yield str(name), lvl


def _academic_responses(program: str = "", dummy: bool = False):
    """-> (list of responses, counts-by-respondent-type dict). Each response is
    {"type", "skills": {key: display}, "weights": {key: 0-1}, "subjects": {code: {key: 0-1}}}
    and only responses that named at least one taught/learned skill are kept.
    Subjects are keyed by code alone: BSIT and BSCS share some subjects, and a
    shared code counts as one subject. `program` ("BSIT"/"BSCS") keeps
    students/alumni of that course and professor subjects in that curriculum.
    `dummy` picks the data set: real answers (default) or only the answers of
    dummy (test) accounts -- the two are never mixed."""
    from . import curriculum_data

    index = _ontology_index()
    by_code = curriculum_data.subject_by_code()
    out = []
    by_type = {"student": 0, "alumni": 0, "professor": 0}
    rows = list(CurriculumSurveyResponse.objects.filter(is_dummy=dummy).order_by("created_at", "pk").values_list("respondent_type", "data", "user_id"))
    # Anyone with an account has one current record per side (learner / professor) --
    # their latest response, which they can edit on My subjects & skills -- so older
    # ones don't count twice.
    def side(rtype):
        return "professor" if rtype == "professor" else "learner"
    latest = {}
    for i, (rtype, _, uid) in enumerate(rows):
        if uid:
            latest[(uid, side(rtype))] = i
    for i, (respondent_type, data, uid) in enumerate(rows):
        if uid and latest[(uid, side(respondent_type))] != i:
            continue
        if not isinstance(data, dict):
            continue
        course = str((data.get("personal_info") or {}).get("course") or "")
        if program and respondent_type != "professor" and course != program:
            continue
        skills, weights, subjects = {}, {}, {}

        def add(entries, subject_key=None):
            for raw, lvl in _skill_entries(entries):
                hit = _standardize(raw, index)
                if not hit:
                    continue
                k, disp = hit
                w = level_weight(lvl)
                skills.setdefault(k, disp)
                weights[k] = max(weights.get(k, 0.0), w)
                if subject_key:
                    per = subjects.setdefault(subject_key, {})
                    per[k] = max(per.get(k, 0.0), w)

        for subj in data.get("subjects") or []:
            if not isinstance(subj, dict):
                continue
            code = str(subj.get("code") or "")
            programs = by_code[code]["programs"] if code in by_code else (subj.get("programs") or [])
            if program and program not in programs:
                continue
            add(subj.get("skills"), code)
        add(data.get("overall_skills"))  # alumni-only field; no-op otherwise
        if not skills:
            continue
        out.append({"type": respondent_type, "skills": skills, "weights": weights, "subjects": subjects})
        if respondent_type in by_type:
            by_type[respondent_type] += 1
    return out, by_type


def _mean(values):
    return sum(values) / len(values) if values else None


def _pct(v):
    return None if v is None else round(v * 100, 1)


# ---------------------------------------------------------------------------
# Per-subject breakdown
# ---------------------------------------------------------------------------
def _by_subject(responses, industry_pct, industry_label, under_taught_keys, program=""):
    """One row per curriculum subject that has survey data or an ontology-suggested
    under-taught skill. industry_pct: {key: % of postings} for every industry skill."""
    from . import curriculum_data, ontology

    index = _ontology_index()
    suggestions = ontology.subject_skill_map()
    lookup = curriculum_data.subject_by_code()

    reported = {}  # code -> {key: {"professor": [w], "learner": [w]}}
    respondents = {}
    for resp in responses:
        group = "professor" if resp["type"] == "professor" else "learner"
        for subj_key, per in resp["subjects"].items():
            respondents[subj_key] = respondents.get(subj_key, 0) + 1
            bucket = reported.setdefault(subj_key, {})
            for k, w in per.items():
                bucket.setdefault(k, {"professor": [], "learner": []})[group].append(w)

    rows = []
    for code, info in lookup.items():
        if program and program not in info["programs"]:
            continue
        subj_reported = reported.get(code, {})
        covered = []
        for k, groups in subj_reported.items():
            if k not in industry_pct:
                continue
            depth = _mean(groups["professor"] + groups["learner"])
            covered.append({
                "skill": industry_label[k],
                "industry_pct": industry_pct[k],
                "depth_pct": _pct(depth),
                "taught_depth_pct": _pct(_mean(groups["professor"])),
                "learned_proficiency_pct": _pct(_mean(groups["learner"])),
                "_depth": depth,
            })
        missing = []
        for name in suggestions.get(code, []):
            hit = _standardize(name, index)
            if hit and hit[0] in under_taught_keys and hit[0] not in subj_reported:
                missing.append({"skill": industry_label.get(hit[0], hit[1]), "industry_pct": industry_pct[hit[0]]})
        if not covered and not missing:
            continue
        demand_total = sum(r["industry_pct"] for r in covered) + sum(r["industry_pct"] for r in missing)
        demand_met = sum(r["industry_pct"] * r["_depth"] for r in covered)
        for r in covered:
            del r["_depth"]
        covered.sort(key=lambda r: -r["industry_pct"])
        missing.sort(key=lambda r: -r["industry_pct"])
        rows.append({
            "code": code,
            "name": info["name"],
            "term_label": info["term_label"],
            "respondents": respondents.get(code, 0),
            # No respondent reported this subject yet -> no alignment to show, only suggestions.
            "alignment_pct": (round(demand_met / demand_total * 100, 1)
                              if demand_total and code in respondents else None),
            "covered": covered[:MAX_SUBJECT_SKILLS],
            "could_add": missing[:MAX_SUBJECT_SKILLS],
        })
    rows.sort(key=lambda r: (r["alignment_pct"] is None, r["alignment_pct"] or 0, r["code"]))
    return rows


# ---------------------------------------------------------------------------
# Put it together
# ---------------------------------------------------------------------------
def compute(top: int = 10, source: str = "", level: str = "", program: str = "", dummy: bool = False) -> dict:
    """Numbers behind the Dashboard's "Alignment score" / "High-priority skill
    gaps" stat cards and the Skill Gap Analysis tab. `top` / `source` / `level`
    match the same controls already used for the Top-in-demand-skills tab, so the
    two stay in sync — this always looks at hard skills only (see module docstring).
    `program` ("BSIT"/"BSCS", blank = both) narrows the academic side; `dummy`
    uses dummy accounts' answers instead of the real ones."""
    top = max(1, min(int(top), 30))
    industry_jobs, info = _industry_mentions(source, level)
    if not info["exists"]:
        return {"exists": False}

    industry_counts, industry_label = _tally(industry_jobs)
    total_postings = len(industry_jobs)
    industry_ranked = sorted(industry_counts.items(), key=lambda kv: (-kv[1], industry_label[kv[0]].lower()))
    top_n = industry_ranked[:top]
    industry_pct = {k: (round(c / total_postings * 100, 1) if total_postings else 0.0)
                    for k, c in industry_counts.items()}

    responses, by_type = _academic_responses(program, dummy)
    total_responses = len(responses)
    has_survey_data = total_responses > 0
    mention_counts, weight_sums = {}, {}
    taught, learned = {}, {}
    for resp in responses:
        for k, w in resp["weights"].items():
            mention_counts[k] = mention_counts.get(k, 0) + 1
            weight_sums[k] = weight_sums.get(k, 0.0) + w
            (taught if resp["type"] == "professor" else learned).setdefault(k, []).append(w)

    industry_vec = [c for _, c in top_n]
    academic_vec = [weight_sums.get(k, 0.0) for k, _ in top_n]
    dot = sum(a * b for a, b in zip(industry_vec, academic_vec))
    mag_i = math.sqrt(sum(a * a for a in industry_vec))
    mag_a = math.sqrt(sum(a * a for a in academic_vec))
    cosine = (dot / (mag_i * mag_a)) if (mag_i and mag_a) else 0.0

    rows = []
    for k, c in top_n:
        academic_c = mention_counts.get(k, 0)
        academic_pct = round(weight_sums.get(k, 0.0) / total_responses * 100, 1) if total_responses else 0.0
        rows.append({
            "skill": industry_label[k],
            "industry_count": c,
            "industry_pct": industry_pct[k],
            "academic_count": academic_c,
            "academic_mention_pct": round(academic_c / total_responses * 100, 1) if total_responses else 0.0,
            "academic_pct": academic_pct,
            "taught_depth_pct": _pct(_mean(taught.get(k, []))),
            "learned_proficiency_pct": _pct(_mean(learned.get(k, []))),
            "gap_score": round(industry_pct[k] - academic_pct, 1),
        })

    under_taught = sorted(
        (r for r in rows if r["gap_score"] > 0),
        key=lambda r: (-r["gap_score"], -r["industry_count"]),
    )[:MAX_LISTED]
    well_covered = sorted(
        (r for r in rows if r["academic_count"] > 0),
        key=lambda r: (-r["academic_pct"], -r["industry_count"]),
    )[:MAX_LISTED]

    # Every in-demand skill with a positive gap (not only the top N) can be proposed for a subject.
    under_taught_keys = {
        k for k in industry_counts
        if industry_pct[k] - (weight_sums.get(k, 0.0) / total_responses * 100 if total_responses else 0.0) > 0
    }

    return {
        "exists": True,
        "program": program,
        "has_survey_data": has_survey_data,
        "survey_responses": total_responses,
        "survey_responses_by_type": by_type,
        "postings_considered": total_postings,
        "alignment_score": round(cosine * 100, 1),
        "alignment_cosine": round(cosine, 3),
        "under_taught": under_taught,
        "well_covered": well_covered,
        "top_gap": under_taught[0]["skill"] if under_taught else None,
        "by_subject": _by_subject(responses, industry_pct, industry_label, under_taught_keys, program)
                      if has_survey_data else [],
    }


# ---------------------------------------------------------------------------
# Per-subject targets (Recommendations page, professor view)
# ---------------------------------------------------------------------------
def subject_targets(code: str, limit: int = 12, info: dict | None = None, dummy: bool = False) -> dict:
    """Which in-demand skills a professor could teach (more deeply) in one subject:
    the subject's curated skills (skills_catalog / subject_skills.py) that appear in
    job postings, ranked by priority = demand % x (1 - depth already reported for
    this subject). Works without any survey data (depth is then simply unknown).
    `info` ({"name", "term_label"}) describes a subject a professor added that isn't
    in the curriculum list; its skills are then suggested from its title."""
    from . import curriculum_data, skills_catalog

    info = info or curriculum_data.subject_by_code().get(code)
    if not info:
        return {"exists": False, "error": "Unknown subject."}
    industry_jobs, meta = _industry_mentions()
    if not meta["exists"]:
        return {"exists": False, "error": "No job-market data yet."}
    counts, label = _tally(industry_jobs)
    total = len(industry_jobs)
    index = _ontology_index()

    responses, _ = _academic_responses(dummy=dummy)
    depth_here = {}
    for resp in responses:
        for k, w in resp["subjects"].get(code, {}).items():
            depth_here.setdefault(k, []).append(w)

    rows, seen = [], set()
    for name in skills_catalog.suggestions_for(info["name"]):
        hit = _standardize(name, index)
        if not hit or hit[0] in seen:
            continue
        k = hit[0]
        seen.add(k)
        c = counts.get(k, 0)
        if not c:
            continue
        pct = round(c / total * 100, 1)
        depth = _mean(depth_here.get(k, []))
        rows.append({
            "skill": label.get(k, name),
            "industry_pct": pct,
            "subject_depth_pct": _pct(depth),
            "reported_by": len(depth_here.get(k, [])),
            "priority": round(pct * (1 - (depth or 0.0)), 2),
        })
    rows.sort(key=lambda r: (-r["priority"], -r["industry_pct"]))
    return {
        "exists": True,
        "code": code,
        "name": info["name"],
        "term_label": info["term_label"],
        "respondents": sum(1 for r in responses if code in r["subjects"]),
        "targets": rows[:limit],
    }
