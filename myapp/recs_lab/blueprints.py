"""
Layer B: what a subject is FOR.

A blueprint per curriculum subject:
  core         concepts the subject must build, each with a target depth
               (introduced / practiced / applied) and other names it may be reported under
  slots        needs that ANY one skill of a family fills ("one general-purpose language")
  extensions   optional extras, suggested only once the core is landing
  out_of_scope things never suggested here (shown so the faculty know why)

Status:
  auto      drafted by plain code from the curated subject list (subject_skills.py) and
            the skill tags (taxonomy.py). Never saved until someone edits or approves it.
  draft     saved: re-drafted by Gemini or edited by a developer, not approved yet
  approved  a developer approved it

Saved in data/.state/recs_lab_blueprints.json, keyed by subject code.
"""
from django.utils import timezone

from .. import curriculum_data, skills_catalog
from . import store, taxonomy

TARGETS = {"introduced": 1 / 3, "practiced": 2 / 3, "applied": 1.0}
TARGET_LABELS = {"introduced": "Introduced", "practiced": "Practiced", "applied": "Applied"}
# Families that are nice to have but never a requirement of a subject.
OPTIONAL_FAMILIES = {"ide", "pm-tools", "office", "os", "spreadsheet", "design-tools", "network-sim"}
UPPER_YEAR_CORE = 5   # 3rd/4th-year subjects: the first N curated concepts are core, the rest extensions


def subjects():
    """[{"code", "name", "programs", "year", "term_label"}] for every subject that gets a
    blueprint: the curriculum minus elective placeholders and practicum / research /
    capstone / thesis subjects (their content changes every term)."""
    lookup = curriculum_data.subject_lookup()
    out = []
    for code, info in curriculum_data.subject_by_code().items():
        if code in curriculum_data.HIDDEN_FROM_PROFESSORS:
            continue
        years = {p: lookup[(p, code)]["year"] for p in info["programs"] if (p, code) in lookup}
        out.append({"code": code, "name": info["name"], "programs": info["programs"],
                    "years": years, "year": min(years.values()) if years else None,
                    "term_label": info["term_label"]})
    out.sort(key=lambda s: (s["year"] or 9, s["code"]))
    return out


def subject(code):
    return next((s for s in subjects() if s["code"] == code), None)


def _clean_list(items, limit=40):
    out, seen = [], set()
    for x in items or []:
        name = " ".join(str(x or "").split())[:80]
        if name and taxonomy.key_of(name) not in seen:
            seen.add(taxonomy.key_of(name))
            out.append(name)
    return out[:limit]


def normalize(bp, info):
    """A blueprint dict with every field present and cleaned."""
    fams = taxonomy.families()
    core = []
    for c in bp.get("core") or []:
        if isinstance(c, str):
            c = {"name": c}
        if not isinstance(c, dict) or not str(c.get("name") or "").strip():
            continue
        target = str(c.get("target") or "practiced").lower()
        core.append({"name": " ".join(str(c["name"]).split())[:80], "also": _clean_list(c.get("also"), 8),
                     "target": target if target in TARGETS else "practiced"})
    slots = []
    for s in bp.get("slots") or []:
        if not isinstance(s, dict):
            continue
        fam = str(s.get("family") or "")
        if fam not in fams:
            continue
        try:
            count = max(1, min(3, int(s.get("count") or 1)))
        except (TypeError, ValueError):
            count = 1
        slots.append({"label": " ".join(str(s.get("label") or fams[fam]["label"]).split())[:80], "family": fam,
                      "count": count, "optional": bool(s.get("optional")), "options": _clean_list(s.get("options"), 20)})
    return {
        "code": info["code"], "name": info["name"],
        "status": bp.get("status") if bp.get("status") in ("auto", "draft", "approved") else "draft",
        "source": bp.get("source") or "manual",
        "core": core[:30], "slots": slots[:10],
        "extensions": _clean_list(bp.get("extensions"), 30),
        "out_of_scope": _clean_list(bp.get("out_of_scope"), 20),
        "notes": " ".join(str(bp.get("notes") or "").split())[:600],
        "updated_at": bp.get("updated_at") or "", "approved_at": bp.get("approved_at") or "",
        "approved_by": bp.get("approved_by") or "",
    }


def auto_draft(info):
    """Blueprint from the curated subject list and the skill tags, no Gemini."""
    tagger = taxonomy.Tagger()
    curated = skills_catalog.suggestions_for(info["name"])
    concepts, by_family, extensions = [], {}, []
    for name in curated:
        t = tagger(name)
        if t["family"]:
            by_family.setdefault(t["family"], []).append(name)
        elif t["kind"] == "concept":
            concepts.append(name)
        else:
            extensions.append(name)
    upper = (info.get("year") or 1) >= 3
    core = [{"name": n, "also": [], "target": "practiced"} for n in (concepts[:UPPER_YEAR_CORE] if upper else concepts)]
    if upper:
        extensions = concepts[UPPER_YEAR_CORE:] + extensions
    slots = []
    fams = taxonomy.families()
    for fam, names in by_family.items():
        kind = fams[fam]["kind"]
        if fam in OPTIONAL_FAMILIES:
            slots.append({"label": fams[fam]["label"], "family": fam, "count": 1, "optional": True, "options": names})
        elif len(names) >= 2 or kind == "language":
            slots.append({"label": fams[fam]["label"], "family": fam, "count": 1, "optional": False, "options": names})
        else:
            extensions.extend(names)
    slots.sort(key=lambda s: (s["optional"], s["label"]))
    return normalize({"status": "auto", "source": "auto", "core": core, "slots": slots, "extensions": extensions,
                      "out_of_scope": [], "notes": ""}, info)


def get(code, info=None):
    info = info or subject(code)
    if not info:
        return None
    saved = store.load("blueprints").get(code)
    if isinstance(saved, dict):
        return normalize(saved, info)
    return auto_draft(info)


def all_blueprints():
    """{code: blueprint} for every subject (saved or auto-drafted)."""
    saved = store.load("blueprints")
    out = {}
    for info in subjects():
        s = saved.get(info["code"])
        out[info["code"]] = normalize(s, info) if isinstance(s, dict) else auto_draft(info)
    return out


def save(code, bp, status="draft", source="manual", user=None):
    info = subject(code)
    if not info:
        raise ValueError("Unknown subject.")
    clean = normalize({**bp, "status": status, "source": source}, info)
    clean["updated_at"] = timezone.now().isoformat(timespec="seconds")
    if status == "approved":
        clean["approved_at"] = clean["updated_at"]
        clean["approved_by"] = user.get_full_name() if user else ""
    store.update("blueprints", lambda data: data.__setitem__(code, clean))
    return clean


def approve(code, user=None):
    bp = get(code)
    if not bp:
        raise ValueError("Unknown subject.")
    return save(code, bp, status="approved", source=bp["source"], user=user)


def reset(code):
    store.update("blueprints", lambda data: data.pop(code, None))


# ---------------------------------------------------------------------------
# The edit form: one item per line, fields separated by "|"
# ---------------------------------------------------------------------------
def to_text(bp):
    return {
        "core": "\n".join(f"{c['name']} | {', '.join(c['also'])} | {c['target']}" for c in bp["core"]),
        "slots": "\n".join(f"{s['label']} | {s['family']} | {s['count']} | {'optional' if s['optional'] else 'required'}"
                           f" | {', '.join(s['options'])}" for s in bp["slots"]),
        "extensions": "\n".join(bp["extensions"]),
        "out_of_scope": "\n".join(bp["out_of_scope"]),
        "notes": bp["notes"],
    }


def from_text(form):
    """-> (blueprint dict, list of problems). Bad lines are reported, not silently dropped."""
    problems = []
    fams = taxonomy.families()
    core = []
    for ln in str(form.get("core") or "").splitlines():
        if not ln.strip():
            continue
        parts = [p.strip() for p in ln.split("|")]
        target = (parts[2].lower() if len(parts) > 2 and parts[2] else "practiced")
        if target not in TARGETS:
            problems.append(f'Core "{parts[0]}": depth must be introduced, practiced or applied.')
            target = "practiced"
        core.append({"name": parts[0], "also": [a for a in (parts[1].split(",") if len(parts) > 1 else []) if a.strip()],
                     "target": target})
    slots = []
    for ln in str(form.get("slots") or "").splitlines():
        if not ln.strip():
            continue
        parts = [p.strip() for p in ln.split("|")]
        fam = parts[1] if len(parts) > 1 else ""
        if fam not in fams:
            problems.append(f'Slot "{parts[0]}": "{fam}" is not a known family key.')
            continue
        slots.append({"label": parts[0] or fams[fam]["label"], "family": fam,
                      "count": parts[2] if len(parts) > 2 else 1,
                      "optional": len(parts) > 3 and parts[3].lower().startswith("opt"),
                      "options": [o for o in (parts[4].split(",") if len(parts) > 4 else []) if o.strip()]})
    lines = lambda f: [ln for ln in str(form.get(f) or "").splitlines() if ln.strip()]
    return {"core": core, "slots": slots, "extensions": lines("extensions"), "out_of_scope": lines("out_of_scope"),
            "notes": form.get("notes") or ""}, problems
