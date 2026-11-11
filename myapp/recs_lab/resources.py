"""
Learning resources for the Recommendations Lab.

What Gemini is asked for depends on who it is for and why (the "purpose"), not just the skill:

  learners (students and alumni)
    start     not learned yet, or only Introduced        -> beginner courses, videos, tutorials
    practice  at Introduced, needs Practiced             -> practice platforms, labs, small projects
    deepen    already Practiced or Applied               -> guided projects, certifications
    preview   a later subject will teach it              -> one short free introduction
    upskill   alumni who need it for a job               -> practical courses, labs, certifications
  professors
    class_landing  taught, but students don't reach Practiced -> classroom activities, exercise sets, tools
    class_add      in the blueprint, nobody reports it        -> open syllabi, lecture materials, lesson plans
    class_deeper   taught below the blueprint's target        -> project briefs, case studies, datasets, rubrics
    self_academy   a required slot is open                    -> academy programs with ready curriculum
    self_training  an extension or curriculum gap to add      -> faculty trainings, certifications

Results are saved per (audience, purpose, skill) in data/.state/recs_lab_resources.json, so many people
with the same need share one Gemini call. Pages never call Gemini: they show what is saved, and the
"Find resources" button queues what is missing for the background worker (worker.py).

Every link is opened before it is kept (recommendations.verify_resource, the same check the site uses)
and each resource's picture is taken from its own page (og:image), never from Gemini, because Gemini
makes image links up. No picture -> the page shows a tile with an icon for the resource type.
"""
import html
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

from django.utils import timezone

from .. import recommendations
from . import store, taxonomy

FILE = "resources"

PURPOSES = {
    "start": ("learner", "Start here"),
    "practice": ("learner", "Practice"),
    "deepen": ("learner", "Go further"),
    "preview": ("learner", "Optional preview"),
    "upskill": ("learner", "Upskill"),
    "class_landing": ("professor", "For your class"),
    "class_add": ("professor", "For your class"),
    "class_deeper": ("professor", "For your class"),
    "self_academy": ("professor", "For you"),
    "self_training": ("professor", "For you"),
}

_ASK = {
    "start": ("a university IT/CS student who has not learned it yet, or only at an introductory level",
              "beginner-friendly online courses, video lessons, official tutorials or documentation, and interactive "
              "practice. Free or free-to-audit first."),
    "practice": ("a student who knows the basics and must get to the point of using it on their own",
                 "practice platforms, hands-on labs or sandboxes, guided exercises and small projects."),
    "deepen": ("a student who can already use it",
               "guided projects, intermediate courses, and entry-level industry certifications a fresh graduate can take."),
    "preview": ("a student whose university subject will teach it next term",
                "one or two short, free introductions only (a video, a tutorial or interactive practice)."),
    "upskill": ("a fresh graduate who needs it for a job",
                "practical courses, hands-on labs, a portfolio project, and entry-level certifications."),
    "class_landing": ("a professor who already teaches it, but most students don't reach the point of using it on "
                      "their own", "classroom activities, exercise sets, auto-graded labs and teaching tools (for "
                      "example code visualizers) to use WITH students. Not courses for the professor."),
    "class_add": ("a professor whose subject plan includes it, but it isn't taught yet",
                  "open syllabi, lecture materials, lesson plans, and open or free textbook chapters."),
    "class_deeper": ("a professor who teaches it only at an introductory level but should take students further",
                     "project briefs, case studies, real datasets, lab activities and rubrics."),
    "self_academy": ("a university department that must add a skill of this kind to a subject",
                     "academy or educator programs that give universities free curriculum, labs and instructor "
                     "training (vendor academies, educator programs), plus instructor training for the skill."),
    "self_training": ("a professor who wants to start teaching it",
                      "faculty or instructor trainings, educator programs and industry certifications."),
}

TYPES = {
    "course": "Course", "video": "Video", "docs": "Docs", "practice": "Practice", "lab": "Lab",
    "project": "Project", "certification": "Certification", "program": "Program", "training": "Training",
    "book": "Book", "roadmap": "Roadmap", "event": "Event", "tool": "Teaching tool", "exercises": "Exercises",
    "syllabus": "Syllabus",
}
# icon group per type (the tile shown when there is no picture)
TYPE_GROUP = {"course": "learn", "video": "learn", "docs": "learn", "book": "learn", "syllabus": "learn",
              "roadmap": "learn", "practice": "do", "lab": "do", "project": "do", "exercises": "do",
              "tool": "do", "certification": "cert", "program": "cert", "training": "cert", "event": "cert"}
COSTS = {"free": "Free", "audit": "Free to audit", "paid": "Paid", "": ""}
LEVELS = ("beginner", "intermediate", "advanced")

_SYSTEM = (
    "You find REAL, currently available learning resources for a Philippine university's IT/CS department "
    "(University of the East). Use web search. Never invent a resource or a URL: if you are not sure a resource "
    "is real, leave it out. Every link is opened automatically and resources whose page doesn't exist or doesn't "
    "show that exact name are thrown away, so give the resource's own page (not a homepage or a search page) and "
    "its exact title. Prefer reputable providers: official documentation and vendor learning sites, Coursera, edX, "
    "freeCodeCamp, Khan Academy, The Odin Project, CS50, well-known YouTube channels, practice sites such as "
    "HackerRank, Exercism or SQLZoo, and free Philippine government trainings (DICT, TESDA Online Program) when "
    "they fit. Answer with ONLY a JSON object, no markdown:\n"
    '{"resources": [{"type": "...", "name": "...", "provider": "...", "link": "...", "cost": "...", '
    '"level": "...", "why": "...", "local": false}]}\n'
    f'"type" is one of: {", ".join(TYPES)}. "cost" is "free", "audit" (free to audit, paid certificate) or "paid". '
    '"level" is beginner, intermediate or advanced. "why" is one short sentence (under 110 characters) on why it '
    'fits this person. "local" is true only for Philippine providers. Return 3 to 6 resources.'
)


def key(purpose, skill):
    return f"{PURPOSES[purpose][0]}|{purpose}|{taxonomy.key_of(skill)}"


def spec(purpose, skill, context=""):
    """One request: what to find, for whom. `context` (a subject or job role) only shapes the prompt."""
    return {"key": key(purpose, skill), "purpose": purpose, "skill": skill, "context": context[:160]}


# ---------------------------------------------------------------------------
# Saved results
# ---------------------------------------------------------------------------
def saved():
    return store.load(FILE).get("entries") or {}


def items_for(k, limit=3, free_only=False, data=None):
    """Saved resources for one key, free first. -> list (empty when none saved yet)."""
    entry = (data if data is not None else saved()).get(k) or {}
    items = [i for i in entry.get("items") or [] if not i.get("hidden")]
    if free_only:
        items = [i for i in items if i.get("cost") in ("free", "audit")]
    items.sort(key=lambda i: (i.get("cost") not in ("free", "audit"), i.get("verified") != "ok",
                              not i.get("local")))
    return [decorate(i) for i in items[:limit]]


def decorate(i):
    """Display fields for one saved resource."""
    return {**i, "type_label": TYPES.get(i.get("type"), "Course"), "group": TYPE_GROUP.get(i.get("type"), "learn"),
            "cost_label": COSTS.get(i.get("cost") or "", ""),
            "meta": " · ".join(x for x in (i.get("provider"), COSTS.get(i.get("cost") or "", ""),
                                            i.get("level")) if x)}


def attach(target, sp, limit, free_only=False, data=None, field="resources"):
    """Puts saved resources (and the request, for the Find button) on a view row."""
    target[field] = items_for(sp["key"], limit, free_only, data)
    target[field + "_spec"] = sp
    target[field + "_label"] = PURPOSES[sp["purpose"]][1]
    target[field + "_saved"] = sp["key"] in (data if data is not None else saved())
    return target


def save_entry(sp, items, error=""):
    def fn(data):
        entries = data.setdefault("entries", {})
        entries[sp["key"]] = {"purpose": sp["purpose"], "skill": sp["skill"], "context": sp.get("context", ""),
                              "items": items, "error": error,
                              "generated_at": timezone.now().isoformat(timespec="seconds")}
    store.update(FILE, fn)


def delete_entry(k):
    store.update(FILE, lambda data: (data.setdefault("entries", {}).pop(k, None)))


def hide_item(k, link):
    def fn(data):
        for i in (data.get("entries") or {}).get(k, {}).get("items") or []:
            if i.get("link") == link:
                i["hidden"] = True
    store.update(FILE, fn)


# ---------------------------------------------------------------------------
# Finding resources (called by the worker only)
# ---------------------------------------------------------------------------
class NothingFound(Exception):
    pass


def _clean(r):
    if not isinstance(r, dict) or not r.get("name") or not r.get("link"):
        return None
    t = str(r.get("type") or "").strip().lower()
    t = t if t in TYPES else next((k for k in TYPES if k in t), "course")
    cost = str(r.get("cost") or "").strip().lower()
    cost = "free" if cost.startswith("free") and "audit" not in cost else "audit" if "audit" in cost else (
        "paid" if cost.startswith("paid") else "")
    level = str(r.get("level") or "").strip().lower()
    return {"type": t, "name": " ".join(str(r["name"]).split())[:160],
            "provider": " ".join(str(r.get("provider") or "").split())[:80],
            "link": str(r["link"]).strip()[:500], "cost": cost, "level": level if level in LEVELS else "",
            "why": " ".join(str(r.get("why") or "").split())[:160], "local": bool(r.get("local"))}


_IMG_RX = (
    re.compile(r'<meta[^>]+(?:property|name)=["\'](?:og:image(?::secure_url)?|twitter:image(?::src)?)["\'][^>]*>', re.I),
    re.compile(r'<link[^>]+rel=["\']image_src["\'][^>]*>', re.I),
)
_ATTR_RX = re.compile(r'(?:content|href)=["\']([^"\']+)["\']', re.I)


def page_image(link):
    """The resource's own preview picture (og:image / twitter:image), checked to be a real image. -> URL or ""."""
    import requests

    try:
        with requests.get(link, headers=recommendations._BROWSER_HEADERS, timeout=recommendations.VERIFY_TIMEOUT,
                          allow_redirects=True, stream=True) as r:
            if r.status_code >= 400 or "html" not in r.headers.get("Content-Type", ""):
                return ""
            body = b""
            for chunk in r.iter_content(32_768):
                body += chunk
                if len(body) >= 300_000 or b"</head>" in body.lower():
                    break
            page_url, encoding = r.url, r.encoding or "utf-8"
    except requests.RequestException:
        return ""
    head = body.decode(encoding, errors="replace")
    url = ""
    for rx in _IMG_RX:
        for tag in rx.findall(head):
            m = _ATTR_RX.search(tag)
            if m:
                url = urljoin(page_url, html.unescape(m.group(1).strip()))
                break
        if url:
            break
    if not url or urlparse(url).scheme != "https":
        return ""
    try:
        with requests.get(url, headers=recommendations._BROWSER_HEADERS, timeout=recommendations.VERIFY_TIMEOUT,
                          stream=True) as r:
            ok = r.status_code < 400 and r.headers.get("Content-Type", "").startswith("image/")
    except requests.RequestException:
        return ""
    return url[:500] if ok else ""


HOMEPAGE_TYPES = {"tool", "practice", "program", "roadmap"}   # a whole site can be the resource (e.g. a code visualizer)


def _homepage_verdict(link, name):
    """verify_resource() rejects bare homepages (Gemini gives them when it has no real course link). For
    tools, practice sites and programs the homepage IS the resource, so check it loads and names itself."""
    import requests

    try:
        with requests.get(link, headers=recommendations._BROWSER_HEADERS, timeout=recommendations.VERIFY_TIMEOUT,
                          allow_redirects=True, stream=True) as r:
            if r.status_code in (404, 410):
                return "dead"
            if r.status_code >= 400:
                return "unknown"
            body = b""
            for chunk in r.iter_content(32_768):
                body += chunk
                if len(body) >= recommendations.VERIFY_MAX_BYTES:
                    break
            text = html.unescape(body.decode(r.encoding or "utf-8", errors="replace")).lower()
    except requests.exceptions.ConnectionError:
        return "dead"
    except requests.RequestException:
        return "unknown"
    return "ok" if recommendations._page_mentions(text, name) else "dead"


def _check(item):
    parsed = urlparse(item["link"])
    if item["type"] in HOMEPAGE_TYPES and parsed.scheme in ("http", "https") and not parsed.path.strip("/") and not parsed.query:
        verdict = _homepage_verdict(item["link"], item["name"])
    else:
        verdict = recommendations.verify_resource(item["link"], item["name"])
    if verdict == "dead":
        return None
    return {**item, "verified": verdict, "image": page_image(item["link"])}


def find(sp, ask=None):
    """Asks Gemini (with web search) for one request, checks every link and finds each picture.
    -> list of resources. Raises NothingFound or gemini.LabGeminiError."""
    from . import gemini

    who, what = _ASK[sp["purpose"]]
    prompt = (f'Skill: "{sp["skill"]}"\nFor: {who}.\n'
              + (f"Context: {sp['context']}\n" if sp.get("context") else "")
              + f"Find: {what}")
    answer = (ask or gemini.ask_search)(_SYSTEM, prompt)
    raw = answer.get("resources") if isinstance(answer, dict) else None
    items = [c for c in (_clean(r) for r in (raw or [])[:8]) if c]
    seen, unique = set(), []
    for i in items:
        if i["link"] not in seen:
            seen.add(i["link"])
            unique.append(i)
    if not unique:
        raise NothingFound("Gemini returned no usable resources.")
    with ThreadPoolExecutor(max_workers=len(unique)) as pool:
        kept = [c for c in pool.map(_check, unique) if c]
    if not kept:
        raise NothingFound("None of the suggested links led to a real page.")
    kept.sort(key=lambda i: i["verified"] != "ok")
    return kept


# ---------------------------------------------------------------------------
# Which request each row of a page gets
# ---------------------------------------------------------------------------
STUDENT_PLAN = {"build_now": ("start", 3), "building": ("practice", 2), "coming_up": ("preview", 1), "met": ("deepen", 2)}
ALUMNI_PLAN = {"build_now": ("upskill", 3), "building": ("practice", 2), "met": ("deepen", 1)}
FACULTY_PLAN = {"not_landing": ("class_landing", 3), "watch": ("class_landing", 2), "not_reported": ("class_add", 3),
                "deepen": ("class_deeper", 3), "open": ("self_academy", 3), "optional": ("self_training", 2)}


def plan_student(result, free_only=False):
    data, specs = saved(), []
    ctx = result.get("role_label") or ""
    for u in result.get("units") or []:
        purpose, n = STUDENT_PLAN[u["status"]]
        sp = spec(purpose, u["pick_skill"], ctx)
        attach(u, sp, n, free_only, data)
        specs.append(sp)
    return specs


def plan_alumni(result, free_only=False):
    data, specs = saved(), []
    ctx = result.get("role_label") or result.get("current_role") or ""
    for u in result.get("units") or []:
        purpose, n = ALUMNI_PLAN[u["status"]]
        sp = spec(purpose, u["pick_skill"], ctx)
        attach(u, sp, n, free_only, data)
        specs.append(sp)
    for w in result.get("wants") or []:
        sp = spec("deepen" if w["status"] == "met" else "practice" if w["status"] == "building" else "upskill",
                  w["skill"], ctx)
        attach(w, sp, 2, free_only, data)
        specs.append(sp)
    return specs


def _faculty_skill(row):
    if row["kind"] == "Slot":
        if row["status"] == "not_landing":
            return (row.get("filled") or "").split(",")[0].strip() or None
        return (row.get("options") or [{}])[0].get("skill")
    return row["item"]


def plan_faculty(result):
    data, specs = saved(), {}
    ctx = f"{result['info']['code']} {result['info']['name']}"
    rows = result.get("core", []) + result.get("slots", []) + result.get("extensions", [])
    for r in rows:
        plan = FACULTY_PLAN.get(r["status"])
        skill = _faculty_skill(r) if plan else None
        if not plan or not skill:
            continue
        sp = spec(plan[0], skill, ctx)
        attach(r, sp, plan[1], data=data)
        specs[sp["key"]] = sp
    for c in result.get("cards") or []:
        plan = FACULTY_PLAN.get(c["status"])
        skill = _faculty_skill(c) if plan else None
        if plan and skill:
            sp = spec(plan[0], skill, ctx)
            attach(c, sp, plan[1], data=data)
            specs[sp["key"]] = sp
    return list(specs.values())


def plan_admin(rows):
    data, specs = saved(), []
    for r in rows:
        if not r.get("home"):
            continue
        purpose = "self_academy" if r["home"]["where"] == "slot" else "self_training"
        sp = spec(purpose, r["members"][0]["skill"], f"{r['home']['code']} {r['home']['name']}")
        attach(r, sp, 1, data=data)
        specs.append(sp)
    return specs
