"""
UEnvision — the skill suggestions shown under each subject in the curriculum surveys
(student, alumni, professor) and on My subjects & skills.

Only the ORDER and the choice of suggested skills change here; the respondent can still
search for any skill, their saved answers are untouched, and nothing here is used for
counting (the gap analysis keeps using ontology.subject_skill_map() as before, and job
posting counts come straight from the extracted skills data set).

For each subject, in this order, without duplicates (capitals / spacing / punctuation ignored):
  1. skills that faculty already reported for that subject in the Professor Survey
     (real answers only; the most-reported first),
  2. the hand-curated list for the subject (subject_skills.py), most in-demand in the
     job postings first (ties keep the curated order),
  3. for a subject without a curated list (the Professional Electives): skills matched from
     words in the subject's title (KEYWORD_SKILLS), then the most in-demand skills overall.
Subjects a respondent adds themselves get the title matches in the browser
(curriculum-survey.js titleSuggestions, from KEYWORD_SKILLS).
"""
import time
from collections import Counter

MAX_SUGGESTIONS = 16
MAX_FROM_FACULTY = 8
CACHE_SECONDS = 300

# Words in a subject title -> skills to suggest. Every name here is also in a curated
# subject list, so it is in the skills catalog and lines up with the gap analysis.
KEYWORD_SKILLS = [
    (("database", "data management", "information management", "sql"),
     ["SQL", "MySQL", "PostgreSQL", "Database Design", "Microsoft SQL Server", "NoSQL", "MongoDB"]),
    (("web", "internet", "front-end", "frontend", "back-end", "backend", "full stack", "fullstack"),
     ["HTML", "CSS", "JavaScript", "PHP", "React", "Node.js", "REST API", "Laravel"]),
    (("mobile", "android", "ios", "app development"),
     ["Android", "Flutter", "Firebase", "REST API", "Java", "JavaScript"]),
    (("network", "networking", "cisco", "communication"),
     ["Computer Networking", "TCP/IP", "Cisco Packet Tracer", "Routing", "Switching", "Network Security", "Subnetting"]),
    (("security", "cyber", "assurance", "forensic"),
     ["Information Security", "Network Security", "Cryptography", "Penetration Testing", "Kali Linux", "Wireshark", "OWASP"]),
    (("cloud", "devops", "infrastructure"),
     ["Cloud Computing", "Docker", "Git", "Linux"]),
    (("data", "analytics", "business intelligence", "visualization", "statistic"),
     ["Data Analysis", "Python", "pandas", "SQL", "Power BI", "Tableau", "Microsoft Excel", "Data Visualization"]),
    (("artificial intelligence", "intelligent", "machine learning", "deep learning", " ai", "neural"),
     ["Machine Learning", "Python", "NumPy", "pandas"]),
    (("game", "graphics", "multimedia", "animation"),
     ["C#", "C++", "Figma", "User Interface Design"]),
    (("human computer", "interaction", "user experience", "ux", "ui ", "design thinking"),
     ["User Experience", "User Interface Design", "Figma", "Usability Testing", "Wireframing", "Prototyping"]),
    (("software engineering", "software development", "systems analysis", "system analysis", "capstone", "project"),
     ["Git", "Agile", "Unit Testing", "Design Patterns", "Object-Oriented Programming", "REST API"]),
    (("operating system", "systems administration", "system administration", "platform"),
     ["Linux", "Windows", "Operating Systems", "Troubleshooting"]),
    (("programming", "programming language", "object-oriented", "object oriented"),
     ["Python", "Java", "C++", "C#", "Object-Oriented Programming", "Git", "Debugging"]),
    (("enterprise", "business", "process", "erp"),
     ["ERP", "Business Process Modeling", "Microsoft Excel", "SQL"]),
]

_cache = {"at": 0.0, "value": None}


def _key(name):
    from . import gap_analysis
    hit = gap_analysis._standardize(str(name or ""))
    return hit[0] if hit else ""


def _dedupe(names):
    seen, out = set(), []
    for n in names:
        k = _key(n)
        if k and k not in seen:
            seen.add(k)
            out.append(n)
    return out


def title_matches(title):
    """Skills suggested by words in a subject title ("Advanced Database Systems" -> SQL, ...)."""
    t = " " + str(title or "").lower() + " "
    out = []
    for words, skills in KEYWORD_SKILLS:
        if any(w in t for w in words):
            out.extend(skills)
    return _dedupe(out)


def _demand():
    """{skill key: number of IT/CS job postings asking for it} (read-only, from the extracted data set)."""
    from . import gap_analysis, job_roles
    postings = job_roles.it_postings(exclude_ghosts=False)
    if not postings:
        return {}
    counts, _ = gap_analysis._tally(p["hard"] for p in postings)
    return counts


def _top_in_demand(demand, limit=12):
    from . import gap_analysis, job_roles
    postings = job_roles.it_postings(exclude_ghosts=False) or []
    _, label = gap_analysis._tally(p["hard"] for p in postings)
    ranked = sorted(demand.items(), key=lambda kv: (-kv[1], label.get(kv[0], kv[0]).lower()))
    return [label.get(k, k) for k, _ in ranked[:limit]]


def _faculty_reported():
    """{subject code: Counter({skill name: number of professors})} from the latest real
    Professor Survey answer of each faculty member."""
    from .models import CurriculumSurveyResponse

    latest = {}
    rows = (CurriculumSurveyResponse.objects
            .filter(respondent_type=CurriculumSurveyResponse.PROFESSOR, is_dummy=False)
            .order_by("created_at", "pk").values_list("user_id", "pk", "data"))
    for user_id, pk, data in rows:
        latest[user_id or f"anon-{pk}"] = data   # later answers replace earlier ones
    out = {}
    for data in latest.values():
        for subj in (data or {}).get("subjects") or []:
            if not isinstance(subj, dict) or not subj.get("code"):
                continue
            seen = set()
            for s in subj.get("skills") or []:
                name = str((s or {}).get("name") or "").strip() if isinstance(s, dict) else ""
                k = _key(name)
                if name and k and k not in seen:
                    seen.add(k)
                    out.setdefault(subj["code"], Counter())[name] += 1
    return out


def ranked_subject_skill_map():
    """{"CODE": [suggested skill names, best first]} for every subject in the catalog."""
    now = time.time()
    if _cache["value"] is not None and now - _cache["at"] < CACHE_SECONDS:
        return _cache["value"]
    from . import curriculum_data, ontology

    base = ontology.subject_skill_map()
    demand = _demand()
    faculty = _faculty_reported()
    top = None
    out = {}
    for code, info in curriculum_data.subject_by_code().items():
        curated = list(base.get(code) or [])
        if curated:
            # most in-demand first; sorted() is stable, so ties keep the curated order
            rest = sorted(curated, key=lambda n: -demand.get(_key(n), 0))
        else:
            if top is None:
                top = _top_in_demand(demand)
            rest = title_matches(info.get("name", "")) + top
        from_faculty = [n for n, _ in faculty.get(code, Counter()).most_common(MAX_FROM_FACULTY)]
        out[code] = _dedupe(from_faculty + rest)[:MAX_SUGGESTIONS]
    _cache.update(at=now, value=out)
    return out


def keyword_table():
    """KEYWORD_SKILLS for the browser (subjects respondents add themselves)."""
    return [[list(words), list(skills)] for words, skills in KEYWORD_SKILLS]


def clear_cache():
    _cache.update(at=0.0, value=None)
