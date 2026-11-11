"""
The Recommendations Lab engine: plain code, no Gemini.

Inputs
  * job postings: job_roles.it_postings() counted with gap_analysis._tally, so every
    skill's share is the same number the rest of the site shows for the same postings.
    By default only entry-level postings (Entry / Junior / Intern ...) count, falling back
    to all postings when there are fewer than MIN_ENTRY_POSTINGS of them.
  * survey answers: each account's latest record (subject_profiles._current_rows).
  * blueprints.py and taxonomy.py.

"Learned" is always the SHARE of learners who reached Practiced or higher (weight >= 0.5,
the student dashboard's rule), never an average level, so a few strong answers can't hide
a class that didn't get it.

  faculty_view(code)     per-subject statuses from the blueprint
  admin_gaps()           top curriculum gaps + coverage by category and year
  student_view(user)     slot-aware next skills for a target role
  alumni_view(user)      upskilling from their own answers and their target role
"""
import re

from .. import curriculum_data, gap_analysis, job_roles, skill_categories, subject_profiles
from ..models import CurriculumSurveyResponse, CustomUser
from . import blueprints, taxonomy

STRONG = 0.5                 # Practiced or Applied (Intermediate+ on the older scale)
LANDING = 0.5                # share of learners at Practiced+ below which a taught item is "not landing"
ON_TRACK = 0.7               # share at or above which it is "on track" (between: "watch")
ENTRY_RX = re.compile(r"entry|junior|intern|fresh|trainee|graduate", re.I)
MIN_ENTRY_POSTINGS = 20
DEFAULT_FLOOR = 3.0          # % of postings a skill (or family) needs to qualify as a curriculum gap
YEAR_MARKET_WEIGHT = {1: 0.0, 2: 0.5, 3: 1.0, 4: 1.0}
TOP_ROLE_SKILLS = 15
LEVEL_WORD = {1 / 3: "Introduced", 2 / 3: "Practiced", 1.0: "Applied"}


def level_word(w):
    if w is None:
        return ""
    return subject_profiles.level_name(w)


def pct(n, d):
    return round(n / d * 100) if d else 0


# ---------------------------------------------------------------------------
# Job postings
# ---------------------------------------------------------------------------
def demand(program="", entry_only=True, role=""):
    """-> None when there is no extracted data, else {"postings", "scope", "entry_postings",
    "counts": {key: n}, "label": {key: display}, "pct": {key: %}}. scope: "entry" / "all" /
    "all_fallback" (asked for entry-level but there were too few)."""
    every = job_roles.it_postings(program=program)
    if every is None:
        return None
    chosen = [p for p in every if not role or p["role"] == role]
    entry = [p for p in chosen if ENTRY_RX.search(p.get("level") or "")]
    scope = "all"
    if entry_only:
        if len(entry) >= MIN_ENTRY_POSTINGS:
            chosen, scope = entry, "entry"
        else:
            scope = "all_fallback"
    counts, label = gap_analysis._tally(p["hard"] for p in chosen)
    total = len(chosen)
    return {"postings": total, "scope": scope, "entry_postings": len(entry), "counts": counts, "label": label,
            "pct": {k: (round(c / total * 100, 1) if total else 0.0) for k, c in counts.items()}}


# ---------------------------------------------------------------------------
# Survey answers
# ---------------------------------------------------------------------------
def _parse(data):
    """-> (subjects {code: {key: weight}}, anywhere {key: weight}, names {key: display})"""
    subjects, anywhere, names = {}, {}, {}

    def add(entries, code=None):
        for raw, lvl in gap_analysis._skill_entries(entries):
            hit = gap_analysis._standardize(raw)
            if not hit:
                continue
            k, disp = hit
            w = gap_analysis.level_weight(lvl)
            names.setdefault(k, disp)
            anywhere[k] = max(anywhere.get(k, 0.0), w)
            if code:
                per = subjects.setdefault(code, {})
                per[k] = max(per.get(k, 0.0), w)

    for subj in data.get("subjects") or []:
        if isinstance(subj, dict) and subj.get("code"):
            add(subj.get("skills"), str(subj["code"]))
    add(data.get("overall_skills"))
    return subjects, anywhere, names


def responses(dummy=False):
    """Each account's latest record: [{"type", "user_id", "course", "subjects", "anywhere",
    "names", "employment"}]."""
    out = []
    for rtype, data, uid in subject_profiles._current_rows(dummy):
        subjects, anywhere, names = _parse(data)
        out.append({"type": rtype, "user_id": uid,
                    "course": str((data.get("personal_info") or {}).get("course") or ""),
                    "subjects": subjects, "anywhere": anywhere, "names": names,
                    "employment": data.get("employment") if isinstance(data.get("employment"), dict) else {}})
    return out


def learners_of(resps, program=""):
    return [r for r in resps if r["type"] != CurriculumSurveyResponse.PROFESSOR and (not program or r["course"] == program)]


# ---------------------------------------------------------------------------
# Faculty: one subject against its blueprint
# ---------------------------------------------------------------------------
STATUS = {
    "not_landing": ("Not landing", "bad"),
    "not_reported": ("Not reported", "warn"),
    "open": ("Slot open", "warn"),
    "deepen": ("Teach it deeper", "warn"),
    "watch": ("Watch", "warn"),
    "on_track": ("On track", "ok"),
    "filled": ("Filled", "ok"),
    "not_enough": ("Not enough answers yet", "mute"),
    "optional_open": ("Optional, not taught", "mute"),
    "after_core": ("Optional, after core", "mute"),
    "optional": ("Optional extension", "info"),
    "covered": ("Covered", "ok"),
}
CARD_TITLE = {
    "not_landing": "Core, not landing", "not_reported": "Core, not reported", "open": "Slot open",
    "deepen": "Teach it deeper", "filled": "Slot filled", "slot_not_landing": "Slot, not landing",
}
ACTION_ORDER = ["not_landing", "not_reported", "open", "deepen"]


def _status(key):
    label, tone = STATUS[key]
    return {"status": key, "status_label": label, "tone": tone}


def professors_for(code, dummy=False):
    """[(user_id, name)] of professors whose latest Professor Survey lists this subject."""
    ids = [r["user_id"] for r in responses(dummy) if r["type"] == CurriculumSurveyResponse.PROFESSOR
           and code in r["subjects"] and r["user_id"]]
    users = {u.pk: u.get_full_name() or u.email for u in CustomUser.objects.filter(pk__in=ids)}
    return [(i, users.get(i, f"Professor #{i}")) for i in ids]


def faculty_view(code, professor_id=None, dummy=False):
    info = blueprints.subject(code)
    if not info:
        return {"exists": False, "error": "Unknown subject."}
    bp = blueprints.get(code, info)
    resps = responses(dummy)
    learners = [r for r in resps if r["type"] != CurriculumSurveyResponse.PROFESSOR and code in r["subjects"]]
    profs = [r for r in resps if r["type"] == CurriculumSurveyResponse.PROFESSOR and code in r["subjects"]]
    if professor_id:
        profs = [r for r in profs if r["user_id"] == professor_id]
    n = len(learners)
    need = subject_profiles.min_respondents()
    enough = n >= need
    who = "You teach" if professor_id else "Taught here"
    year = info["year"] or 1
    d = demand(program=info["programs"][0] if len(info["programs"]) == 1 else "", entry_only=True)
    dpct = d["pct"] if d else {}
    dlabel = d["label"] if d else {}

    def evidence(keys):
        taught = [p["subjects"][code][k] for p in profs for k in keys if k in p["subjects"][code]]
        reported = [max(l["subjects"][code][k] for k in keys if k in l["subjects"][code])
                    for l in learners if any(k in l["subjects"][code] for k in keys)]
        strong = sum(1 for w in reported if w >= STRONG)
        return (max(taught) if taught else None), len(reported), strong

    in_blueprint = set()
    core_rows = []
    for c in bp["core"]:
        keys = {taxonomy.key_of(x) for x in [c["name"]] + c["also"]}
        in_blueprint |= keys
        taught_w, reported, strong = evidence(keys)
        share = strong / n if n else 0.0
        target_w = blueprints.TARGETS[c["target"]]
        lw = level_word(taught_w)
        if not enough:
            st = "not_enough"
            why = (f"Only {n} student{'s' if n != 1 else ''} answered for this subject; at least {need} are needed."
                   + (f" {who} at {lw}." if taught_w is not None else ""))
        elif taught_w is not None and share < LANDING:
            st = "not_landing"
            why = (f"{who} at {lw}. Only {strong} of {n} students ({pct(strong, n)}%) reached Practiced. "
                   "A short hands-on lab or graded exercise may help it stick.")
        elif taught_w is None and reported == 0:
            st = "not_reported"
            why = ("In the blueprint, but no professor or student reported it here. Check whether it's taught "
                   "under another name, or add it.")
        elif taught_w is not None and taught_w < target_w - 1e-6:
            st = "deepen"
            why = (f"{who} at {lw}, but the blueprint target is {blueprints.TARGET_LABELS[c['target']]}. "
                   f"{strong} of {n} students reached Practiced.")
        elif share < ON_TRACK:
            st = "watch"
            why = f"{strong} of {n} students ({pct(strong, n)}%) reached Practiced."
        else:
            st = "on_track"
            why = f"{strong} of {n} students ({pct(strong, n)}%) reached Practiced."
        core_rows.append({"item": c["name"], "kind": "Concept", "target": blueprints.TARGET_LABELS[c["target"]],
                          "taught": lw or "Not reported", "taught_w": taught_w, "reported": reported, "strong": strong,
                          "n": n, "share": pct(strong, n) if n else None, "why": why, **_status(st)})

    known_names = list(dlabel.values())
    slot_rows = []
    for s in bp["slots"]:
        members = taxonomy.family_members(s["family"], known_names + s["options"])
        for o in s["options"]:
            members.setdefault(taxonomy.key_of(o), o)
        in_blueprint |= set(members)
        per = []
        for k, name in members.items():
            taught_w, reported, strong = evidence({k})
            if taught_w is not None or reported:
                per.append({"key": k, "skill": dlabel.get(k, name), "taught_w": taught_w, "reported": reported,
                            "strong": strong})
        filled = [m for m in per if m["taught_w"] is not None or m["reported"] >= need]
        any_strong = sum(1 for l in learners if any(l["subjects"][code].get(k, 0) >= STRONG for k in members))
        options = sorted(({"skill": dlabel.get(k, name), "pct": dpct.get(k, 0.0)} for k, name in members.items()),
                         key=lambda o: -o["pct"])
        options = [o for o in options if o["pct"] > 0][:4] or [{"skill": o, "pct": 0.0} for o in s["options"][:4]]
        if filled:
            best = max(filled, key=lambda m: (m["taught_w"] or 0, m["strong"]))
            names = ", ".join(m["skill"] for m in filled[:3])
            tw = level_word(best["taught_w"])
            if enough and any_strong / n < LANDING:
                st, card = "not_landing", "slot_not_landing"
                why = (f"{names} {'is' if len(filled) == 1 else 'are'} {'taught' if tw else 'reported'} here"
                       f"{' at ' + tw if tw else ''}, but only {any_strong} of {n} students ({pct(any_strong, n)}%) "
                       "reached Practiced in any of them.")
            else:
                st, card = "filled", "filled"
                why = (f"Filled by {names}" + (f" ({who.lower()} at {tw})" if tw else "")
                       + (f". {any_strong} of {n} students ({pct(any_strong, n)}%) reached Practiced" if n else "")
                       + f". No second {s['label'].lower()} is suggested.")
            filled_text = names
        else:
            filled_text = ""
            opts = ", ".join(f"{o['skill']} {o['pct']}%" for o in options if o["pct"]) or ", ".join(o["skill"] for o in options)
            if s["optional"]:
                st, card = "optional_open", None
                why = f"Optional. Common choices: {opts}."
            else:
                st, card = "open", "open"
                why = (f"No {s['label'].lower()} is taught or reported here yet. Pick one"
                       + (f". In entry-level postings: {opts}." if any(o["pct"] for o in options) else f": {opts}."))
        slot_rows.append({"item": s["label"] + (f" ×{s['count']}" if s["count"] > 1 else " ×1"), "kind": "Slot",
                          "family": s["family"], "filled": filled_text, "options": options, "optional": s["optional"],
                          "taught": filled_text or "None yet", "n": n, "strong": any_strong,
                          "share": pct(any_strong, n) if n else None, "why": why, "card": card,
                          **_status(st)})

    core_blocked = any(r["status"] in ("not_landing", "not_reported", "deepen") for r in core_rows)
    weight = YEAR_MARKET_WEIGHT.get(year, 1.0)
    ext_rows = []
    for name in bp["extensions"]:
        k = taxonomy.key_of(name)
        in_blueprint.add(k)
        taught_w, reported, strong = evidence({k})
        dem = dpct.get(k, 0.0)
        if taught_w is not None or reported >= need:
            st = "covered"
            why = (f"{who} at {level_word(taught_w)}." if taught_w is not None else f"{reported} students reported it here.")
        elif core_blocked:
            st = "after_core"
            why = "Optional. Suggested only once the core concepts are landing."
        else:
            st = "optional"
            why = (f"In {dem}% of entry-level postings." if dem else "Optional extra for this subject.")
        ext_rows.append({"item": name, "kind": "Extension", "taught": level_word(taught_w) or "Not reported",
                         "n": n, "strong": strong, "share": pct(strong, n) if n else None, "demand": dem,
                         "rank": dem * weight, "why": why, **_status(st)})
    ext_rows.sort(key=lambda r: (r["status"] != "optional", -r["rank"], r["item"].lower()))

    # Skills reported here that the blueprint doesn't mention: a hint to refine the blueprint.
    extra = {}
    for r in profs + learners:
        for k in r["subjects"][code]:
            if k not in in_blueprint:
                extra.setdefault(k, {"skill": r["names"].get(k, k), "people": 0})
                extra[k]["people"] += 1
    extras = sorted(extra.values(), key=lambda e: (-e["people"], e["skill"].lower()))

    rows = core_rows + slot_rows + ext_rows
    actionable = [r for r in core_rows + slot_rows if r["status"] in ACTION_ORDER]
    actionable.sort(key=lambda r: ACTION_ORDER.index(r["status"]))
    cards = []
    for r in actionable[:3]:
        cards.append({**r, "title": CARD_TITLE["slot_not_landing" if r.get("card") == "slot_not_landing" else r["status"]],
                      "name": r["item"] if r["kind"] != "Slot" else r["item"].rsplit(" ×", 1)[0]})
    for r in slot_rows:
        if len(cards) >= 3:
            break
        if r["status"] == "filled":
            cards.append({**r, "title": CARD_TITLE["filled"], "name": f"{r['item'].rsplit(' ×', 1)[0]}: {r['filled']}"})
    return {
        "exists": True, "info": info, "bp": bp, "learners": n, "professors": len(profs), "need": need,
        "enough": enough, "rows": rows, "core": core_rows, "slots": slot_rows, "extensions": ext_rows,
        "cards": cards, "extras": extras[:12], "year_weight": weight,
        "demand_scope": d["scope"] if d else "", "demand_postings": d["postings"] if d else 0,
    }


# ---------------------------------------------------------------------------
# Administrators: top curriculum gaps
# ---------------------------------------------------------------------------
def _homes(all_bps, program=""):
    """{family key or skill key: (code, name, where, year)}: the best subject for a gap."""
    subs = {s["code"]: s for s in blueprints.subjects()}
    found = {}
    rank = {"open slot": 0, "slot": 1, "extension": 2, "core": 3}

    def offer(key, code, where):
        s = subs[code]
        if program and program not in s["programs"]:
            return
        yr = s["years"].get(program) if program else s["year"]
        cand = (rank[where], yr or 9, code)
        if key not in found or cand < found[key][0]:
            found[key] = (cand, {"code": code, "name": s["name"], "where": where, "year": yr})

    for code, bp in all_bps.items():
        for sl in bp["slots"]:
            offer("fam:" + sl["family"], code, "slot")
            for o in sl["options"]:
                offer("skill:" + taxonomy.key_of(o), code, "slot")
        for e in bp["extensions"]:
            offer("skill:" + taxonomy.key_of(e), code, "extension")
        for c in bp["core"]:
            for x in [c["name"]] + c["also"]:
                offer("skill:" + taxonomy.key_of(x), code, "core")
    return {k: v[1] for k, v in found.items()}


def _alumni_mentions(resps):
    """{key: {"needed": n, "used": n}} from alumni employment answers."""
    out = {}
    for r in resps:
        if r["type"] != CurriculumSurveyResponse.ALUMNI:
            continue
        emp = r["employment"]
        needed = set()
        for name in list(emp.get("skills_to_learn") or []) + list(emp.get("upskilling_skills") or []):
            hit = gap_analysis._standardize(name.get("name") if isinstance(name, dict) else name)
            if hit:
                needed.add(hit[0])
        used = set()
        for name in emp.get("skills_applied") or []:
            hit = gap_analysis._standardize(name.get("name") if isinstance(name, dict) else name)
            if hit:
                used.add(hit[0])
        for k in needed:
            out.setdefault(k, {"needed": 0, "used": 0})["needed"] += 1
        for k in used:
            out.setdefault(k, {"needed": 0, "used": 0})["used"] += 1
    return out


def admin_gaps(program="", entry_only=True, floor=DEFAULT_FLOOR, dummy=False, limit=10):
    d = demand(program, entry_only)
    if d is None:
        return {"exists": False}
    tagger = taxonomy.Tagger()
    fams = tagger.fams
    units = {}
    for k, c in d["counts"].items():
        name = d["label"][k]
        t = tagger(name)
        u = ("fam:" + t["family"]) if t["family"] else ("skill:" + k)
        unit = units.setdefault(u, {"unit": u, "members": [], "kind": t["kind"], "kind_label": t["kind_label"],
                                    "label": fams[t["family"]]["label"] if t["family"] else name,
                                    "category": t["category"], "family": t["family"]})
        unit["members"].append({"key": k, "skill": name, "pct": d["pct"][k], "count": c})
    resps = responses(dummy)
    learners = learners_of(resps, program)
    n = len(learners)
    alumni = _alumni_mentions([r for r in resps if not program or r["course"] == program])
    homes = _homes(blueprints.all_blueprints(), program)
    taught_in = {}
    for r in resps:
        if r["type"] == CurriculumSurveyResponse.PROFESSOR:
            for code, per in r["subjects"].items():
                for k in per:
                    taught_in.setdefault(k, set()).add(code)
    rows = []
    for u in units.values():
        u["members"].sort(key=lambda m: (-m["pct"], m["skill"].lower()))
        top = u["members"][0]["pct"]
        if top < floor:
            continue
        keys = {m["key"] for m in u["members"]}
        if u["family"]:
            keys |= set(taxonomy.family_members(u["family"]))
        strong = sum(1 for l in learners if any(l["anywhere"].get(k, 0) >= STRONG for k in keys))
        reported = sum(1 for l in learners if any(k in l["anywhere"] for k in keys))
        cov = strong / n if n else None
        al = {"needed": 0, "used": 0}
        for k in keys:
            a = alumni.get(k)
            if a:
                al["needed"] += a["needed"]
                al["used"] += a["used"]
        subjects_taught = set()
        for k in keys:
            subjects_taught |= taught_in.get(k, set())
        home = homes.get(u["unit"])
        if not home:
            for m in u["members"]:
                home = homes.get("skill:" + m["key"])
                if home:
                    break
        rows.append({**u, "demand": top, "coverage": None if cov is None else round(cov * 100),
                     "strong": strong, "reported": reported, "learners": n,
                     "gap": round(top * (1 - (cov or 0.0)), 2), "alumni_needed": al["needed"], "alumni_used": al["used"],
                     "taught_in": sorted(subjects_taught), "home": home,
                     "members_text": " · ".join(f"{m['skill']} {m['pct']}%" for m in u["members"][:4])
                                     + (f" · +{len(u['members']) - 4} more" if len(u["members"]) > 4 else "")})
    rows.sort(key=lambda r: (-r["gap"], -r["alumni_needed"], r["label"].lower()))
    return {"exists": True, "postings": d["postings"], "scope": d["scope"], "entry_postings": d["entry_postings"],
            "learners": n, "floor": floor, "rows": rows[:limit], "all_rows": rows, "program": program,
            "heat": heatmap(d, learners, program, floor, tagger)}


def heatmap(d, learners, program, floor, tagger):
    """Rows: categories of in-demand skills. Columns: year levels 1-4. A cell is the share of
    learners who answered for a subject of that year and reached Practiced+ there in at least
    one of the category's in-demand skills. "planned": a blueprint of that year covers the category."""
    lookup = curriculum_data.subject_lookup()
    by_code = curriculum_data.subject_by_code()
    cats = {}
    for k, p in d["pct"].items():
        if p >= floor:
            cats.setdefault(tagger(d["label"][k])["category"], set()).add(k)
    if not cats:
        return []

    def year_of(code, course):
        progs = [course] if course in curriculum_data.PROGRAMS else (by_code.get(code, {}).get("programs") or [])
        ys = [lookup[(p, code)]["year"] for p in progs if (p, code) in lookup]
        return min(ys) if ys else None

    per_year = {y: [] for y in curriculum_data.YEAR_LEVELS}
    for l in learners:
        best = {}
        for code, per in l["subjects"].items():
            y = year_of(code, l["course"])
            if y:
                b = best.setdefault(y, {})
                for k, w in per.items():
                    b[k] = max(b.get(k, 0.0), w)
        for y, b in best.items():
            per_year[y].append(b)

    planned = {y: set() for y in curriculum_data.YEAR_LEVELS}
    for code, bp in blueprints.all_blueprints().items():
        s = blueprints.subject(code)
        y = (s["years"].get(program) if program else s["year"]) if s else None
        if not y or (program and program not in s["programs"]):
            continue
        names = [c["name"] for c in bp["core"]] + bp["extensions"] + [o for sl in bp["slots"] for o in sl["options"]]
        for nm in names:
            planned[y].add(tagger(nm)["category"])
    out = []
    for cat in sorted(cats, key=skill_categories.order_key):
        if cat == skill_categories.OTHER:
            continue
        keys = cats[cat]
        cells = []
        for y in curriculum_data.YEAR_LEVELS:
            group = per_year[y]
            v = (sum(1 for b in group if any(b.get(k, 0) >= STRONG for k in keys)) / len(group)) if group else None
            is_planned = cat in planned[y]
            if v is None:
                tone, text = "c0", "no answers" if is_planned else "—"
            elif v == 0 and not is_planned:
                tone, text = "c0", "—"
            else:
                tone = "c3" if v >= 0.5 else "c2" if v >= 0.2 else "c1"
                text = f"{round(v * 100)}%"
            cells.append({"year": y, "tone": tone, "text": text, "planned": is_planned, "learners": len(group)})
        out.append({"category": cat, "skills": len(keys), "cells": cells})
    return out


# ---------------------------------------------------------------------------
# Students and alumni
# ---------------------------------------------------------------------------
def _role_units(d, tagger, top=TOP_ROLE_SKILLS):
    """The role's top skills grouped into units (family or single skill), in demand order."""
    ranked = sorted(d["counts"].items(), key=lambda kv: (-kv[1], d["label"][kv[0]].lower()))[:top]
    units, order = {}, []
    for k, c in ranked:
        name = d["label"][k]
        t = tagger(name)
        u = ("fam:" + t["family"]) if t["family"] else ("skill:" + k)
        if u not in units:
            units[u] = {"unit": u, "label": tagger.fams[t["family"]]["label"] if t["family"] else name,
                        "family": t["family"], "kind_label": t["kind_label"], "members": []}
            order.append(u)
        units[u]["members"].append({"key": k, "skill": name, "pct": d["pct"][k]})
    return [units[u] for u in order]


def _mine_status(unit, mine, known):
    keys = {m["key"] for m in unit["members"]}
    if unit["family"]:
        keys |= set(taxonomy.family_members(unit["family"], known))
    have = [(k, mine[k]) for k in keys if k in mine]
    strong = [(k, m) for k, m in have if m["weight"] >= STRONG]
    pick = max(strong or have, key=lambda km: km[1]["weight"]) if have else None
    return ("met" if strong else "building" if have else "missing"), pick


def student_view(user, dummy=False, role=None):
    """`role`: a job role to preview instead of the student's saved target role (developers)."""
    from .. import rec_context

    ctx = rec_context.student_context(user)
    program, year = ctx["program"], ctx["year"]
    role = role if role is not None else user.target_role
    role = role if role in job_roles.ROLE_LABELS else ""
    d = demand(program, entry_only=True, role=role)
    if d is None:
        return {"exists": False}
    if role and not d["postings"]:
        role = ""
        d = demand(program, entry_only=True)
    tagger = taxonomy.Tagger()
    units = _role_units(d, tagger)
    known = list(d["label"].values())

    later = {}
    if program and year:
        current = curriculum_data.student_eligible_terms(program, year)[0]
        terms = curriculum_data.later_terms(program, current["key"]) if current else []
        for term in terms:
            for subj in curriculum_data.learner_subjects_for_term(program, term["key"]):
                bp = blueprints.get(subj["code"])
                if not bp:
                    continue
                for sl in bp["slots"]:
                    later.setdefault("fam:" + sl["family"], (subj["name"], term["label"]))
                for nm in [c["name"] for c in bp["core"]] + bp["extensions"] + [o for sl in bp["slots"] for o in sl["options"]]:
                    later.setdefault("skill:" + taxonomy.key_of(nm), (subj["name"], term["label"]))

    met = 0
    for u in units:
        st, pick = _mine_status(u, ctx["mine"], known)
        u["pick_skill"] = pick[1]["skill"] if pick else u["members"][0]["skill"]
        u["members_text"] = ", ".join(f"{m['skill']} {m['pct']}%" for m in u["members"][:4])
        u["top_pct"] = u["members"][0]["pct"]
        if st == "met":
            met += 1
            m = pick[1]
            u.update(status="met", status_label="Need met", tone="ok",
                     why=f"You have {m['skill']} at {m.get('level') or 'Practiced'}"
                         + (" (assumed from earlier subjects)" if m.get("assumed") else "") + ".")
        elif st == "building":
            m = pick[1]
            u.update(status="building", status_label="Keep building", tone="warn",
                     why=f"You have {m['skill']} at {m.get('level') or 'Introduced'}. Practice it until you reach Practiced.")
        else:
            home = later.get(u["unit"]) or next((later.get("skill:" + mm["key"]) for mm in u["members"]
                                                 if later.get("skill:" + mm["key"])), None)
            if home:
                u.update(status="coming_up", status_label=f"Coming up in {home[0]}", tone="info",
                         why=f"Planned in {home[0]} ({home[1]}).")
            else:
                u.update(status="build_now", status_label="Build now", tone="bad",
                         why="No subject you've taken or will take covers it. Learn one on your own.")
    order = {"build_now": 0, "building": 1, "coming_up": 2, "met": 3}
    units.sort(key=lambda u: (order[u["status"]], -u["top_pct"]))
    return {"exists": True, "user": user, "program": program, "year": year, "term": ctx.get("term", ""),
            "role": role, "role_label": job_roles.ROLE_LABELS.get(role, ""), "postings": d["postings"], "scope": d["scope"],
            "units": units, "met": met, "readiness": pct(met, len(units)) if units else None,
            "assumed": len(ctx.get("assumed") or {})}


def alumni_view(user, dummy=False, role=None):
    from ..student_views import _my_skills, latest_response

    latest = latest_response(user)
    data = latest.data if latest else {}
    emp = (data or {}).get("employment") or {}
    mine = _my_skills(user)
    program = str(((data or {}).get("personal_info") or {}).get("course") or (user.learner_info or {}).get("course") or "")
    program = program if program in curriculum_data.PROGRAMS else ""
    role = role if role is not None else user.target_role
    role = role if role in job_roles.ROLE_LABELS else ""
    d = demand(program, entry_only=False, role=role)
    if d is None:
        return {"exists": False}
    if role and not d["postings"]:
        role = ""
        d = demand(program, entry_only=False)
    tagger = taxonomy.Tagger()
    known = list(d["label"].values())

    applied = []
    mine = dict(mine)
    for name in emp.get("skills_applied") or []:
        name = name.get("name") if isinstance(name, dict) else name
        hit = gap_analysis._standardize(name or "")
        if hit:
            applied.append(hit[1])
            # A skill used at work counts as Applied for their role needs.
            if hit[0] not in mine or mine[hit[0]]["weight"] < 1:
                mine[hit[0]] = {"skill": hit[1], "level": "Applied (used at work)", "weight": 1.0}

    wants = []
    for name in list(emp.get("skills_to_learn") or []) + list(emp.get("upskilling_skills") or []):
        name = name.get("name") if isinstance(name, dict) else name
        hit = gap_analysis._standardize(name or "")
        if not hit or any(w["key"] == hit[0] for w in wants):
            continue
        k, disp = hit
        have = mine.get(k)
        wants.append({"key": k, "skill": disp, "pct": d["pct"].get(k, 0.0),
                      "status": "met" if have and have["weight"] >= STRONG else "building" if have else "missing",
                      "level": have["level"] if have else ""})
    wants.sort(key=lambda w: -w["pct"])
    units = _role_units(d, tagger)
    met = 0
    for u in units:
        st, pick = _mine_status(u, mine, known)
        u["pick_skill"] = pick[1]["skill"] if pick else u["members"][0]["skill"]
        u["members_text"] = ", ".join(f"{m['skill']} {m['pct']}%" for m in u["members"][:4])
        u["top_pct"] = u["members"][0]["pct"]
        if st == "met":
            met += 1
            u.update(status="met", status_label="Need met", tone="ok",
                     why=f"You have {pick[1]['skill']} at {pick[1].get('level') or 'Practiced'}.")
        elif st == "building":
            u.update(status="building", status_label="Keep building", tone="warn",
                     why=f"You have {pick[1]['skill']} at {pick[1].get('level') or 'Introduced'}.")
        else:
            u.update(status="build_now", status_label="Upskill", tone="bad", why="Not in your answers yet.")
    order = {"build_now": 0, "building": 1, "met": 2}
    units.sort(key=lambda u: (order[u["status"]], -u["top_pct"]))
    return {"exists": True, "user": user, "program": program, "employment": emp,
            "employed": emp.get("status") == "employed", "current_role": emp.get("current_role") or "",
            "role": role, "role_label": job_roles.ROLE_LABELS.get(role, ""), "postings": d["postings"], "units": units,
            "met": met, "readiness": pct(met, len(units)) if units else None, "wants": wants, "applied": applied}
