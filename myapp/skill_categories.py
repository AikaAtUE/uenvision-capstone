"""
UEnvision — skill categories for display (e.g. Agile = Software development methods,
SQL = Databases & SQL), as the adviser asked.

This only labels skills so the dashboard can group them. It never merges, renames or
recounts anything: the counts still come straight from hard_skills.csv and the
surveys. A skill's category comes from a few keyword rules first (for skills the MIND
ontology doesn't list, like Agile or Linux), then from the MIND Tech Skills Ontology's
"type" / "technicalDomains" columns, and otherwise it is "Other".
"""
import re

OTHER = "Other"

# Checked in order; the first rule whose pattern matches the skill name wins.
KEYWORD_RULES = [
    ("Software development methods", r"\b(agile|scrum|kanban|waterfall|sdlc|software development life ?cycle|"
                                     r"lean|extreme programming|xp|tdd|bdd|ci/?cd|devops practices?)\b"),
    ("Testing & QA", r"\b(test(ing)?|qa|quality assurance|selenium|cypress|jest|pytest|junit|postman)\b"),
    ("Security", r"\b(security|cyber\w*|penetration|vulnerability|firewall|siem|iam|encryption|owasp)\b"),
    ("Networking & operating systems", r"\b(network(ing)?|tcp/?ip|dns|dhcp|lan|wan|vpn|routing|switching|cisco|ccna|"
                                       r"linux|unix|windows server|windows|macos|operating systems?|active directory)\b"),
    ("Data & AI", r"\b(machine learning|deep learning|artificial intelligence|ai|data analysis|data analytics|"
                  r"data science|statistics|excel|power ?bi|tableau|etl|data warehous\w*|big data|nlp|"
                  r"computer vision|pandas|numpy)\b"),
    ("Databases & SQL", r"\b(sql|database|dbms|nosql|mysql|postgres\w*|oracle db|mongodb|data modeling)\b"),
    ("Cloud & DevOps", r"\b(cloud|aws|azure|gcp|google cloud|docker|kubernetes|terraform|jenkins|devops)\b"),
    ("Web development", r"\b(html|css|front-?end|back-?end|web development|node(\.js|js)?|express(\.js)?|rest(ful)?( api)?s?|api|apis|graphql)\b"),
    ("Design & multimedia", r"\b(graphic design|ui/?ux|ux|ui design|figma|photoshop|illustrator|adobe\w*|canva|"
                            r"video editing|multimedia|draw\.io|wireframing)\b"),
    ("Project & business tools", r"\b(jira|confluence|trello|project management|erp|sap|crm|salesforce|"
                                 r"business analysis|ms office|microsoft office)\b"),
]
_COMPILED = [(cat, re.compile(pat, re.I)) for cat, pat in KEYWORD_RULES]

CATEGORY_ORDER = [
    "Programming languages", "Web development", "Databases & SQL", "Data & AI", "Cloud & DevOps",
    "Software development methods", "Testing & QA", "Security", "Networking & operating systems",
    "Frameworks & libraries", "Design & multimedia", "Project & business tools", "Tools & services", OTHER,
]


def _from_ontology(row):
    low = row["_l"]  # the ontology's columns, lowercased (see ontology._load_rows)
    types = {t.strip() for t in low.get("type", "").split("|") if t.strip()}
    domains = low.get("technicalDomains", "")
    if types & {"programminglanguage", "scriptinglanguage"}:
        return "Programming languages"
    if types & {"querylanguage", "database"}:
        return "Databases & SQL"
    if "markuplanguage" in types:
        return "Web development"
    if types & {"protocol", "webserver"}:
        return "Networking & operating systems"
    if "data science" in domains or "machine learning" in domains:
        return "Data & AI"
    if "devops" in domains or "cloud" in domains:
        return "Cloud & DevOps"
    if types & {"framework", "library"}:
        return "Web development" if "frontend" in domains else "Frameworks & libraries"
    if types & {"tool", "service"}:
        return "Tools & services"
    return None


_INDEX = {"rows": None, "index": {}}


def _ontology_index():
    """{lowercased name or synonym: ontology row} for the ontology's skills, rebuilt
    whenever ontology.py reloads its rows."""
    from . import ontology

    rows = ontology._load_rows()
    if _INDEX["rows"] is not rows:
        index = {}
        for row in rows:
            if row.get("record_kind") not in ("", "Skill"):
                continue
            for name in [row["_l"].get("name", "")] + row["_l"].get("synonyms", "").split("|"):
                key = name.strip()
                if key:
                    index.setdefault(key, row)
        _INDEX.update(rows=rows, index=index)
    return _INDEX["index"]


def category_for(skill: str) -> str:
    name = str(skill or "").strip()
    if not name:
        return OTHER
    for cat, rx in _COMPILED:
        if rx.search(name):
            return cat
    try:
        row = _ontology_index().get(name.lower())
    except (OSError, UnicodeDecodeError):
        row = None
    return (_from_ontology(row) if row else None) or OTHER


def order_key(category: str) -> int:
    return CATEGORY_ORDER.index(category) if category in CATEGORY_ORDER else len(CATEGORY_ORDER)
