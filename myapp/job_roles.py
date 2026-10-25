"""
UEnvision — groups scraped job titles into a small set of IT/CS job roles, so the
public homepage and the student/alumni dashboard can show "top skills for the
role you want" instead of one list for every posting.

Postings carry free-text titles ("Fullstack Developer {Java and Spring Boot}
[Hybrid]", "Jr. Network and Computer System Associate", ...). role_for() maps a
title to the first role whose patterns match; titles that match no role (and the
non-IT postings Kalibrr also returns, such as accountants) are left out of the
role statistics. Add or reorder patterns in ROLES to change the grouping.
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


def _postings():
    """-> list of (role_key or None, {skill_key: display}) per extracted posting, cached
    until data/extracted_skills.csv changes."""
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

    index = gap_analysis._ontology_index()
    out = []
    for r in rows:
        skills = {}
        for raw in split_skills(get(r, "hard_skills")):
            hit = gap_analysis._standardize(raw, index)
            if hit:
                skills.setdefault(hit[0], hit[1])
        out.append((role_for(get(r, "job_name"), get(r, "function")), skills))
    _CACHE.update(key=stamp, value=out)
    return out


def _top(postings, top):
    counts, label = {}, {}
    for _, skills in postings:
        for k, disp in skills.items():
            counts[k] = counts.get(k, 0) + 1
            label.setdefault(k, disp)
    total = len(postings)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], label[kv[0]].lower()))
    pct = {k: round(c / total * 100, 1) for k, c in counts.items()} if total else {}
    return [{"key": k, "skill": label[k], "count": c, "pct": pct[k]} for k, c in ranked[:top]], pct


def skill_stats(role="", top=10):
    """Top hard skills across all IT-role postings, and (if `role` is given) for that
    role, each role skill with its overall % for comparison.
    -> {"exists", "roles": [{key, label, postings}], "overall": {...}, "role": {...} or None}"""
    postings = _postings()
    if postings is None:
        return {"exists": False}
    it_postings = [p for p in postings if p[0]]
    counts = {}
    for key, _ in it_postings:
        counts[key] = counts.get(key, 0) + 1
    roles = [{"key": k, "label": label, "postings": counts[k]} for k, label, _ in ROLES if counts.get(k)]
    overall_top, overall_pct = _top(it_postings, top)
    result = {
        "exists": True,
        "roles": roles,
        "overall": {"postings": len(it_postings), "skills": overall_top},
        "role": None,
    }
    if role in ROLE_LABELS:
        role_postings = [p for p in it_postings if p[0] == role]
        role_top, _ = _top(role_postings, top)
        for s in role_top:
            s["overall_pct"] = overall_pct.get(s["key"], 0.0)
        result["role"] = {"key": role, "label": ROLE_LABELS[role], "postings": len(role_postings), "skills": role_top}
    return result
