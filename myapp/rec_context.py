"""
UEnvision — context-aware recommendations: what each student and each subject should
work on next, and why. Plain code over the survey answers, the subject profiles
(subject_profiles.py) and the job postings; Gemini is only used afterwards, by
rec_queue.py, to find learning resources for the skills chosen here.

Student context (student_context / student_plan):
  * reported skills  - their own survey record (student_views._my_skills)
  * assumed skills   - for every subject of an EARLIER year level of their own program that
                       they did not answer for, the skills at least min_respondents people
                       reported there, at those people's average level. They count toward
                       job readiness, are labeled "assumed", and the student can confirm or
                       remove each one (AssumedSkillChoice). They never enter the gap analysis
                       or any count shown from the data sets.
  * year level       - skills a LATER subject of their program builds up are listed as
                       "coming up" instead of being pushed now.
  * target job role  - the role's top skills from the job postings (job_roles.skill_stats,
                       counted as in the data set) are the goal; no role = overall top skills.

Faculty context (faculty_subject): for one subject, per in-demand skill that fits it,
what this professor teaches, what students learned there, how many subjects of earlier
year levels (same program) already build it, and the job-market demand; then a
suggestion (taught but not landing / add it / build on earlier years / teach it deeper /
on track).
"""
from . import curriculum_data, gap_analysis, job_roles, subject_profiles
from .models import AssumedSkillChoice, CustomUser

STRONG_WEIGHT = 0.5          # Practiced or Applied (same rule as the student dashboard)
NOT_LANDING_GAP = 0.2        # students' average level this far below the professor's
FACULTY_LIMIT = 12


def _int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def learner_program_year(user, data=None):
    """(program, year level) from the account's "About you", else from the survey answer."""
    info = user.learner_info or {}
    personal = ((data or {}).get("personal_info") or {}) if isinstance(data, dict) else {}
    program = str(info.get("course") or personal.get("course") or "")
    year = _int(info.get("year_level") or personal.get("year_level"))
    return (program if program in curriculum_data.PROGRAMS else ""), (year if year in curriculum_data.YEAR_LEVELS else None)


def _term_subjects(program, terms):
    """[(subject key, name, code, term label)] for the subjects of these terms."""
    out = []
    for term in terms:
        for subj in curriculum_data.learner_subjects_for_term(program, term["key"]):
            out.append((subject_profiles.canonical(subj["name"]), subj["name"], subj["code"], term["label"]))
    return out


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------
def student_context(user):
    """-> {"program", "year", "reported": {key: {...}}, "assumed": {key: {...}},
    "removed": [{...}], "later": {key: {...}}, "mine": reported + assumed (not removed)}.
    Assumed skills and "later" are only worked out for students whose program and year
    level are known; alumni get their reported skills only (their version comes later)."""
    from .student_views import _my_skills, latest_response

    reported = _my_skills(user)
    out = {"program": "", "year": None, "reported": reported, "assumed": {}, "removed": [], "later": {},
           "mine": dict(reported)}
    if user.role != CustomUser.Role.STUDENT and not (user.is_developer and user.learner_info):
        return out
    latest = latest_response(user)
    data = latest.data if latest else {}
    program, year = learner_program_year(user, data)
    out.update(program=program, year=year)
    if not program or not year:
        return out
    dummy = user.answers_are_dummy
    current, _previous, _summer, earlier = curriculum_data.student_eligible_terms(program, year)
    if current is None:
        return out

    answered = {str(s.get("code")) for s in (data or {}).get("subjects") or [] if isinstance(s, dict)}
    answered_keys = {subject_profiles.canonical(s.get("name") or curriculum_data.subject_by_code().get(str(s.get("code")), {}).get("name", ""))
                     for s in (data or {}).get("subjects") or [] if isinstance(s, dict)}
    earlier_subjects = [(k, n, c, t) for k, n, c, t in _term_subjects(program, earlier)
                        if c not in answered and k not in answered_keys]
    choices = dict(AssumedSkillChoice.objects.filter(user=user).values_list("skill_key", "choice"))
    if earlier_subjects:
        names = {k: (n, t) for k, n, c, t in earlier_subjects}
        for row in subject_profiles.rows_for(program, dummy, subject_keys=names):
            if row.skill_key in reported:
                continue
            w = subject_profiles.stat_depth(row)
            entry = out["assumed"].setdefault(row.skill_key, {"skill": row.skill, "weight": 0.0, "sources": []})
            entry["sources"].append({"subject": names[row.subject_key][0], "term": names[row.subject_key][1],
                                     "people": row.respondents})
            entry["weight"] = max(entry["weight"], w)
        for key, entry in list(out["assumed"].items()):
            entry.update(key=key, level=subject_profiles.level_name(entry["weight"]), assumed=True,
                         confirmed=choices.get(key) == AssumedSkillChoice.CONFIRMED)
            entry["sources"].sort(key=lambda s: (-s["people"], s["subject"]))
            if choices.get(key) == AssumedSkillChoice.REMOVED:
                out["removed"].append(out["assumed"].pop(key))
            else:
                out["mine"][key] = entry

    later = _term_subjects(program, curriculum_data.later_terms(program, current["key"]))
    if later:
        where = {}
        for k, n, c, t in later:
            where.setdefault(k, (n, t))
        for row in subject_profiles.rows_for(program, dummy, subject_keys=where):
            out["later"].setdefault(row.skill_key, {"skill": row.skill, "subject": where[row.subject_key][0],
                                                    "term": where[row.subject_key][1]})
    return out


def status_of(mine, key):
    """("strong" | "building" | "missing", level text, assumed?) for one skill."""
    m = mine.get(key)
    if not m:
        return "missing", "", False
    return ("strong" if m["weight"] >= STRONG_WEIGHT else "building"), m.get("level") or "", bool(m.get("assumed"))


def _reason(s, role_label, ctx):
    """One plain sentence on why this skill is recommended."""
    goal = f"{role_label} job postings" if role_label else "IT/CS job postings"
    m = ctx["mine"].get(s["key"])
    if m and m.get("assumed"):
        src = m["sources"][0]
        return (f"Assumed {m['level']} from {src['subject']} ({src['term']}), as reported by {src['people']} people. "
                f"It is in {s['pct']}% of {goal}, so take it further.")
    if m:
        return f"You rated it {m['level'] or 'below Practiced'}. It is in {s['pct']}% of {goal}; practice it to reach job level."
    return f"It is in {s['pct']}% of {goal}, and none of your subjects so far build it up."


def student_plan(user, top=10, max_to_build=6):
    """Everything the student dashboard shows, from student_context():
    -> {"ctx", "stats", "role", "compare", "overall", "have", "readiness", "to_build", "coming_up"}"""
    ctx = student_context(user)
    stats = job_roles.skill_stats(user.target_role, top)
    role = stats.get("role") if stats.get("exists") else None
    compare = (role["skills"] if role else stats["overall"]["skills"]) if stats.get("exists") else []
    overall = stats["overall"]["skills"] if stats.get("exists") else []
    for s in list(compare) + list(overall):
        s["status"], s["my_level"], s["assumed"] = status_of(ctx["mine"], s["key"])
    have = sum(1 for s in compare if s["status"] == "strong")
    have_assumed = sum(1 for s in compare if s["status"] == "strong" and s["assumed"])
    readiness = round(have / len(compare) * 100) if compare else None
    role_label = role["label"] if role else ""
    to_build, coming_up = [], []
    for s in compare:
        if s["status"] == "strong":
            continue
        later = ctx["later"].get(s["key"])
        if later and s["status"] == "missing":
            coming_up.append({**s, "subject": later["subject"], "term": later["term"]})
            continue
        s["reason"] = _reason(s, role_label, ctx)
        to_build.append(s)
    return {"ctx": ctx, "stats": stats, "role": role, "compare": compare, "overall": overall, "have": have,
            "have_assumed": have_assumed, "readiness": readiness, "to_build": to_build[:max_to_build],
            "coming_up": coming_up}


def gemini_context(role_label, level):
    """What Gemini is told about the learner when it looks for resources."""
    who = f"a university IT/CS student who wants to work as a {role_label}" if role_label else "a university IT/CS student"
    have = f"; their current level in this skill: {level}" if level else "; they have not learned this skill yet"
    return who + have


# ---------------------------------------------------------------------------
# Faculty
# ---------------------------------------------------------------------------
TAGS = {
    "not_landing": "Taught, not landing",
    "add": "In demand, add it",
    "build": "Build on earlier years",
    "deepen": "Teach it deeper",
    "on_track": "On track",
}
ACTIONABLE = ("not_landing", "add", "build", "deepen")


def _subject_programs_years(code, info):
    lookup = curriculum_data.subject_lookup()
    programs = [p for p in (info.get("programs") or []) if p in curriculum_data.PROGRAMS] or list(curriculum_data.PROGRAMS)
    return {p: (lookup.get((p, code)) or {}).get("year") for p in programs}


def _my_levels(user, code):
    """{skill key: (display, weight, level)} this professor reported for this subject."""
    from .student_views import latest_response

    latest = latest_response(user) if user is not None else None
    out = {}
    for subj in ((latest.data or {}).get("subjects") or []) if latest else []:
        if isinstance(subj, dict) and str(subj.get("code")) == code:
            for raw, lvl in gap_analysis._skill_entries(subj.get("skills")):
                hit = gap_analysis._standardize(raw)
                if hit:
                    out[hit[0]] = (hit[1], gap_analysis.level_weight(lvl), str(lvl or "").title())
    return out


def faculty_subject(code, info=None, user=None, dummy=False, limit=FACULTY_LIMIT):
    """-> {"exists", "code", "name", "programs": {program: year}, "rows": [...], "cards": [...],
    "min_respondents"} for one subject. Rows: in-demand skills that fit the subject (its
    suggested skills, what this professor reported, and what anyone reported for it), each
    with taught / learned / earlier / demand and a tag."""
    from . import skills_catalog

    info = info or curriculum_data.subject_by_code().get(code)
    if not info:
        return {"exists": False, "error": "Unknown subject."}
    jobs, meta = gap_analysis._industry_mentions()
    if not meta["exists"]:
        return {"exists": False, "error": "No job-market data yet."}
    counts, label = gap_analysis._tally(jobs)
    total = len(jobs) or 1
    need = subject_profiles.min_respondents()
    key = subject_profiles.canonical(info["name"])
    years = _subject_programs_years(code, info)

    here, earlier = {}, {}
    for program, year in years.items():
        for row in subject_profiles.rows_for(program, dummy, subject_keys=[key], counted_only=False):
            h = here.setdefault(row.skill_key, {"skill": row.skill, "learners": 0, "ldepth": 0.0, "people": 0})
            h["learners"] += row.learners
            h["ldepth"] += (row.learner_depth or 0) * row.learners
            h["people"] = max(h["people"], row.respondents)
        if year:
            for row in subject_profiles.rows_for(program, dummy, year_below=year):
                if row.subject_key == key:
                    continue
                e = earlier.setdefault(row.skill_key, {"subjects": {}, "depth": []})
                e["subjects"][row.subject_key] = row.subject_name
                e["depth"].append(subject_profiles.stat_depth(row))
    mine = _my_levels(user, code)

    candidates = []
    for name in list(skills_catalog.suggestions_for(info["name"])) + [v[0] for v in mine.values()] + [h["skill"] for h in here.values()]:
        hit = gap_analysis._standardize(name)
        if hit and hit[0] not in {c[0] for c in candidates} and counts.get(hit[0]):
            candidates.append(hit)

    rows = []
    for k, display in candidates:
        pct = round(counts[k] / total * 100, 1)
        taught = mine.get(k)
        h = here.get(k)
        learned_n = h["learners"] if h else 0
        learned_w = h["ldepth"] / learned_n if learned_n else None
        e = earlier.get(k)
        e_n = len(e["subjects"]) if e else 0
        e_w = sum(e["depth"]) / len(e["depth"]) if e else None
        taught_w = taught[1] if taught else None
        counted_here = bool(h and h["people"] >= need)
        if taught_w is not None and taught_w >= 2 / 3 and learned_n >= need and learned_w is not None \
                and learned_w < taught_w - NOT_LANDING_GAP:
            tag = "not_landing"
            why = (f"You teach it at {taught[2]}, but {learned_n} student{'s' if learned_n != 1 else ''} rated it "
                   f"{subject_profiles.level_name(learned_w)} here. A hands-on lab or project may help it stick.")
        elif e_n:
            tag = "build"
            why = (f"Already built up in {e_n} earlier subject{'s' if e_n != 1 else ''} of the same program, at about "
                   f"{subject_profiles.level_name(e_w)}, so students are ready for a more advanced take, not an intro.")
        elif taught_w is None and not counted_here:
            tag = "add"
            why = f"In {pct}% of IT/CS job postings, and no earlier subject or survey answer builds it up here yet."
        elif (taught_w if taught_w is not None else (learned_w or 0)) < 2 / 3:
            tag = "deepen"
            why = f"In {pct}% of IT/CS job postings, but it is only introduced here so far."
        else:
            tag = "on_track"
            why = "Taught and learned at Practiced or Applied here."
        depth_here = taught_w if taught_w is not None else (learned_w or 0.0)
        rows.append({
            "key": k, "skill": label.get(k, display), "industry_pct": pct,
            "taught": taught[2] if taught else "", "taught_w": taught_w,
            "learned": subject_profiles.level_name(learned_w) if learned_n else "", "learned_n": learned_n,
            "earlier_n": e_n, "earlier_level": subject_profiles.level_name(e_w) if e_n else "",
            "earlier_subjects": sorted(e["subjects"].values()) if e else [],
            "tag": tag, "tag_label": TAGS[tag], "why": why,
            "priority": round(pct * (1 - depth_here), 2),
        })
    order = {t: i for i, t in enumerate(("not_landing", "add", "build", "deepen", "on_track"))}
    rows.sort(key=lambda r: (r["tag"] == "on_track", -r["priority"], order[r["tag"]], -r["industry_pct"]))
    rows = rows[:limit]
    return {
        "exists": True, "code": code, "name": info["name"], "programs": years,
        "year_label": ", ".join(f"{p} {y}{_ordinal(y)} Year" for p, y in years.items() if y) or info.get("term_label", ""),
        "respondents": max([h["people"] for h in here.values()] or [0]),
        "rows": rows, "cards": [r for r in rows if r["tag"] in ACTIONABLE][:6], "min_respondents": need,
    }


def _ordinal(n):
    return {1: "st", 2: "nd", 3: "rd"}.get(n, "th")
