"""
UEnvision — groups scraped job titles into a small set of IT/CS job roles, so the
public homepage and the student/alumni dashboard can show "top skills for the
role you want" instead of one list for every posting.

Postings carry free-text titles ("Fullstack Developer {Java and Spring Boot}
[Hybrid]", "Jr. Network and Computer System Associate", ...). role_for() maps a
title to the first role whose patterns match; titles that match no role (and the
non-IT postings Kalibrr also returns, such as accountants) are left out of the
role statistics. Add or reorder patterns in ROLES to change the grouping.

postings() / it_postings() are also the ONE place results read job postings from:
the homepage, the student/alumni dashboard, the Dashboard's charts and stat cards,
the skill gap analysis and the Recommendations page all count the same IT/CS
postings with the same skill names (as written in the data set), so a skill's share is
the same number wherever it is shown.
"""
import re

from .pipeline import manager as pipeline
from .pipeline.skills_schema import split_skills

# (key, label, title patterns). Order matters: the first matching role wins.
ROLES = [
    ("ui-ux", "UI/UX Designer", [r"\bui\b", r"\bux\b"]),
    ("qa", "QA / Software Tester", [r"\bqa\b", r"quality assurance", r"\btest(ing|er)\b", r"quality engineer"]),
    ("cybersecurity", "Cybersecurity Analyst / Engineer", [r"secur", r"\bsoc\b"]),
    ("data-science", "Data Scientist / AI-ML Engineer", [r"data scien", r"machine learning", r"\bai\b", r"\bml\b", r"\bllm\b"]),
    ("data-engineering", "Data Engineer / Database", [r"data engineer", r"data architect", r"data warehouse", r"database"]),
    ("data-analyst", "Data Analyst", [r"data analy", r"analytics", r"data management"]),
    ("mobile", "Mobile Developer", [r"android", r"\bios\b", r"mobile developer"]),
    ("devops", "DevOps / Cloud Engineer", [r"devops", r"\bcloud\b", r"site reliability", r"infra"]),
    ("full-stack", "Full-Stack Developer", [r"full ?stack"]),
    ("front-end", "Front-End / Web Developer", [r"front ?end", r"web developer", r"wordpress", r"\baem\b"]),
    ("back-end", "Back-End Developer", [r"back ?end", r"\.net\b", r"python developer", r"oracle (apex|ebs)", r"salesforce developer"]),
    ("software-dev", "Software Developer / Engineer", [r"software (developer|engineer|designer)", r"application developer", r"developer", r"product engineer", r"rpa", r"automation"]),
    ("architect", "Solutions / Software Architect", [r"architect", r"solutions? designer"]),
    ("network-sysad", "Network / Systems Administrator", [r"network", r"system associate", r"computer system", r"data center", r"systems? application engineer", r"operations engineer"]),
    ("it-support", "IT Support / Service Desk", [r"it support", r"it customer support", r"product support", r"technical services", r"service management", r"it and admin"]),
    ("analyst", "Business / Systems Analyst", [r"business analyst", r"systems? analyst", r"information systems analyst", r"business systems"]),
    ("it-pm", "IT Project / Product Manager", [r"scrum master", r"project manager", r"product manager", r"program manager", r"delivery manager"]),
]
ROLE_LABELS = {key: label for key, label, _ in ROLES}
_COMPILED = [(key, [re.compile(p, re.I) for p in pats]) for key, _, pats in ROLES]

# Roles are only assigned to IT postings, or to titles that are unmistakably IT.
IT_FUNCTION = "IT and Software"
_IT_TITLE = re.compile(r"\b(it|software|developer|data|network|cloud|devops|qa|ui|ux|security|system|systems)\b", re.I)

_CACHE = {"key": None, "value": None}


def role_for(title, function=""):
    title = str(title or "")
    if function != IT_FUNCTION and not _IT_TITLE.search(title):
        return None
    for key, pats in _COMPILED:
        if any(p.search(title) for p in pats):
            return key
    return None


def postings():
    """-> one dict per extracted posting, cached until data/extracted_skills.csv changes:
    {"role": role key or None, "source", "level" ("" if not given), "month" ("YYYY-MM" or None),
     "hard": {skill_key: display}, "soft": {skill_key: display}}.
    Skill names are counted as written in the data set, the same way as the survey
    answers (gap_analysis._standardize): "REST APIs" and "RESTful APIs" are two skills,
    "Jira" and "JIRA" are one."""
    from . import gap_analysis

    path = pipeline.extracted_csv()
    try:
        stamp = (path.stat().st_mtime, path.stat().st_size)
    except OSError:
        return None
    if _CACHE["key"] == stamp:
        return _CACHE["value"]
    loaded = pipeline.load_table("extracted")
    if loaded is None:
        return None
    columns, rows = loaded
    idx = {c: i for i, c in enumerate(columns)}

    def get(r, c):
        i = idx.get(c)
        return r[i].strip() if i is not None and i < len(r) else ""

    def skills(raw):
        out = {}
        for name in split_skills(raw):
            hit = gap_analysis._standardize(name)
            if hit:
                out.setdefault(hit[0], hit[1])
        return out

    out = []
    for r in rows:
        m = pipeline._MONTH_RE.match(get(r, "date"))
        out.append({
            "role": role_for(get(r, "job_name"), get(r, "function")),
            "source": get(r, "source"),
            "level": get(r, "experience_level"),
            "month": f"{m.group(1)}-{m.group(2)}" if m else None,
            "hard": skills(get(r, "hard_skills")),
            "soft": skills(get(r, "soft_skills")),
        })
    _CACHE.update(key=stamp, value=out)
    return out


def it_postings(source="", level=""):
    """The postings every result counts: IT/CS-role postings only (non-IT postings that
    the job boards also return, such as accountants or pharmacists, are left out),
    optionally narrowed to one source / experience level ("Not specified" = blank).
    -> list, or None when there's no extracted data yet."""
    all_postings = postings()
    if all_postings is None:
        return None
    return [p for p in all_postings if p["role"]
            and (not source or p["source"] == source)
            and (not level or (p["level"] or "Not specified") == level)]


def _top(postings, top):
    from . import gap_analysis

    counts, label = gap_analysis._tally(p["hard"] for p in postings)
    total = len(postings)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], label[kv[0]].lower()))
    pct = {k: round(c / total * 100, 1) for k, c in counts.items()} if total else {}
    return [{"key": k, "skill": label[k], "count": c, "pct": pct[k]} for k, c in ranked[:top]], pct


def skill_stats(role="", top=10):
    """Top hard skills across all IT-role postings, and (if `role` is given) for that
    role, each role skill with its overall % for comparison.
    -> {"exists", "roles": [{key, label, postings}], "overall": {...}, "role": {...} or None, "source_label"}"""
    it = it_postings()
    if it is None:
        return {"exists": False}
    counts = {}
    for p in it:
        counts[p["role"]] = counts.get(p["role"], 0) + 1
    roles = [{"key": k, "label": label, "postings": counts[k]} for k, label, _ in ROLES if counts.get(k)]
    overall_top, overall_pct = _top(it, top)
    result = {
        "exists": True,
        "roles": roles,
        "overall": {"postings": len(it), "skills": overall_top},
        "role": None,
        # Shown as "According to N job postings from <source_label>" under the charts.
        "source_label": ", ".join(sorted({str(p["source"]).capitalize() for p in it if p["source"]})) or "online job boards",
    }
    if role in ROLE_LABELS:
        role_postings = [p for p in it if p["role"] == role]
        role_top, _ = _top(role_postings, top)
        for s in role_top:
            s["overall_pct"] = overall_pct.get(s["key"], 0.0)
        result["role"] = {"key": role, "label": ROLE_LABELS[role], "postings": len(role_postings), "skills": role_top}
    return result
