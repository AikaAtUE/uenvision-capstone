"""
Layer A: what a skill IS.

Every skill name gets
  * a KIND: concept, language, framework, tool or practice (decides how it is recommended),
  * a FAMILY (languages, frameworks and tools only): skills that can stand in for each
    other, so knowing one of them fills the need ("one general-purpose language"),
  * a CATEGORY for display (reuses skill_categories.category_for).

Where a tag comes from, first match wins:
  1. a developer's manual tag (saved in data/.state/recs_lab_skill_tags.json, source "manual"),
  2. a Gemini tag (same file, source "gemini", see gemini.tag_skills),
  3. the built-in FAMILIES below (matched on the counted name, gap_analysis.count_key),
  4. keyword rules and the MIND ontology's type column,
  5. otherwise "concept".

Tags never change a count. A family is a label; each member keeps its own share of postings.
"""
import re

from .. import gap_analysis, skill_categories
from . import store

KINDS = {
    "concept": "Concept",
    "language": "Language",
    "framework": "Framework / library",
    "tool": "Tool / platform",
    "practice": "Practice / method",
}
INTERCHANGEABLE = {"language", "framework", "tool"}

# (key, label, kind, member names as written in the data sets and the survey catalog)
FAMILIES = [
    ("lang-general", "General-purpose programming language", "language",
     ["Python", "Java", "C", "C++", "C#", "Go", "Golang", "Rust", "Kotlin", "Ruby", "Visual Basic", "VB.NET",
      "Swift", "Scala", "Dart", "Perl"]),
    ("lang-web", "Web programming language", "language", ["JavaScript", "TypeScript", "PHP"]),
    ("html", "HTML", "language", ["HTML", "HTML5"]),
    ("css", "CSS", "language", ["CSS", "CSS3"]),
    ("frontend-fw", "Front-end framework", "framework",
     ["React", "React.js", "ReactJS", "Angular", "AngularJS", "Vue.js", "Vue", "VueJS", "Next.js", "Nuxt.js", "Svelte",
      "jQuery"]),
    ("css-fw", "CSS framework", "framework", ["Bootstrap", "Tailwind CSS", "Tailwind", "Material UI", "Sass"]),
    ("backend-fw", "Back-end framework", "framework",
     ["Spring Boot", "Spring", "Spring Framework", "Django", "Flask", "FastAPI", "Laravel", "CodeIgniter", "ASP.NET",
      "ASP.NET Core", ".NET", ".NET Core", "Express", "Express.js", "Node.js", "NestJS", "Ruby on Rails"]),
    ("mobile-fw", "Mobile app framework", "framework",
     ["Flutter", "React Native", "Android", "Android SDK", "iOS", "Xamarin", "Ionic", "Jetpack Compose", "SwiftUI"]),
    ("desktop-gui", "Desktop GUI toolkit", "framework", ["JavaFX", "Java Swing", "Swing", "Windows Forms", "WPF", "Tkinter"]),
    ("rdbms", "Relational database", "tool",
     ["MySQL", "PostgreSQL", "Microsoft SQL Server", "SQL Server", "MSSQL", "Oracle Database", "Oracle", "SQLite",
      "MariaDB", "IBM Db2"]),
    ("nosql", "NoSQL database", "tool", ["MongoDB", "Firebase", "Firestore", "Redis", "Cassandra", "DynamoDB", "Couchbase"]),
    ("cloud", "Cloud platform", "tool",
     ["AWS", "Amazon Web Services", "Azure", "Microsoft Azure", "Google Cloud Platform", "Google Cloud", "GCP",
      "Oracle Cloud", "IBM Cloud"]),
    ("containers", "Containers", "tool", ["Docker", "Podman"]),
    ("orchestration", "Container orchestration", "tool", ["Kubernetes", "OpenShift", "Docker Swarm"]),
    ("ci-tools", "CI/CD tool", "tool", ["Jenkins", "GitHub Actions", "GitLab CI", "GitLab CI/CD", "Azure DevOps", "CircleCI",
                                        "Bamboo", "Travis CI"]),
    ("vcs", "Version control", "tool", ["Git", "GitHub", "GitLab", "Bitbucket", "SVN", "Subversion"]),
    ("ide", "Code editor / IDE", "tool",
     ["Visual Studio Code", "VS Code", "VSCode", "IntelliJ IDEA", "Eclipse IDE", "Eclipse", "Visual Studio", "Code::Blocks",
      "Dev-C++", "NetBeans", "PyCharm", "Android Studio", "Xcode"]),
    ("bi", "BI / dashboard tool", "tool",
     ["Power BI", "Microsoft Power BI", "Tableau", "Looker", "Looker Studio", "Google Data Studio", "Qlik", "Qlik Sense"]),
    ("spreadsheet", "Spreadsheet", "tool", ["Microsoft Excel", "Excel", "Google Sheets"]),
    ("test-tools", "Testing tool", "tool",
     ["JUnit", "Selenium", "Cypress", "Jest", "Pytest", "Postman", "Playwright", "Mocha", "TestNG", "NUnit"]),
    ("pm-tools", "Project tracking tool", "tool", ["Jira", "Trello", "Asana", "Confluence", "ClickUp", "Monday.com"]),
    ("os", "Operating system", "tool", ["Linux", "Windows", "Windows Server", "macOS", "Unix", "Ubuntu", "Red Hat Linux"]),
    ("diagram-tools", "Diagramming tool", "tool", ["Draw.io", "diagrams.net", "Lucidchart", "Microsoft Visio", "Visio"]),
    ("design-tools", "Design tool", "tool", ["Figma", "Adobe XD", "Photoshop", "Adobe Photoshop", "Illustrator",
                                             "Adobe Illustrator", "Canva", "Sketch"]),
    ("ml-libs", "Machine learning library", "framework", ["TensorFlow", "PyTorch", "Scikit-learn", "scikit-learn", "Keras"]),
    ("data-libs", "Data analysis library", "framework", ["Pandas", "NumPy", "Matplotlib"]),
    ("office", "Office suite", "tool", ["Microsoft Office", "MS Office", "Microsoft Word", "Microsoft PowerPoint",
                                        "Google Workspace", "Google Docs"]),
    ("network-sim", "Network simulator", "tool", ["Cisco Packet Tracer", "Packet Tracer", "GNS3", "Wireshark"]),
]

PRACTICE_RX = re.compile(
    r"\b(agile|scrum|kanban|waterfall|sdlc|software development life ?cycle|lean|six sigma|extreme programming|tdd|bdd|"
    r"test[- ]driven|unit testing|integration testing|code review|ci/?cd|continuous (integration|delivery|deployment)|"
    r"devops|pair programming|documentation|technical writing|requirements (analysis|gathering)|project management|"
    r"change management|itil|incident management|version control|refactoring|clean code|solid principles|"
    r"design patterns?|user research|usability testing|accessibility)\b", re.I)
LANGUAGE_RX = re.compile(r"^(html5?|css3?|sql|t-sql|pl/sql|r|matlab|bash|shell scripting|powershell|assembly|"
                         r"assembly language|lua|haskell|prolog|lisp|cobol|fortran|julia)$", re.I)
# Data formats are concepts, not languages a slot could take.
FORMAT_RX = re.compile(r"^(xml|json|yaml|csv)$", re.I)
TOOL_RX = re.compile(r"\b(server|studio|suite|workbench|tracer)\b", re.I)

_FAMILY_INDEX = None


def key_of(name):
    return gap_analysis.count_key(name)


def _family_index():
    """{counted name: family key} for the built-in families."""
    global _FAMILY_INDEX
    if _FAMILY_INDEX is None:
        idx = {}
        for fkey, _label, _kind, members in FAMILIES:
            for m in members:
                idx.setdefault(key_of(m), fkey)
        _FAMILY_INDEX = idx
    return _FAMILY_INDEX


def saved():
    """{"skills": {count key: {"skill", "kind", "family", "source"}}, "families": {key: {"label", "kind"}}}"""
    data = store.load("skill_tags")
    data.setdefault("skills", {})
    data.setdefault("families", {})
    return data


def families(data=None):
    """{family key: {"label", "kind", "builtin"}} built-in plus the ones Gemini or a developer added."""
    out = {k: {"label": label, "kind": kind, "builtin": True} for k, label, kind, _ in FAMILIES}
    for k, f in (data or saved())["families"].items():
        if k not in out and isinstance(f, dict) and f.get("label"):
            out[k] = {"label": str(f["label"]), "kind": f.get("kind") if f.get("kind") in KINDS else "tool",
                      "builtin": False}
    return out


def family_label(fkey, fams=None):
    f = (fams or families()).get(fkey)
    return f["label"] if f else ""


def _ontology_kind(name):
    try:
        row = skill_categories._ontology_index().get(str(name).strip().lower())
    except (OSError, UnicodeDecodeError):
        row = None
    if not row:
        return None
    types = {t.strip() for t in row["_l"].get("type", "").split("|") if t.strip()}
    if types & {"programminglanguage", "scriptinglanguage", "querylanguage", "markuplanguage"}:
        return "language"
    if types & {"framework", "library"}:
        return "framework"
    if types & {"tool", "service", "database", "webserver", "platform", "operatingsystem"}:
        return "tool"
    return None


def rule_tag(name):
    """(kind, family key or "") from the built-in rules only."""
    k = key_of(name)
    fam = _family_index().get(k, "")
    if fam:
        return next(kind for fk, _l, kind, _m in FAMILIES if fk == fam), fam
    text = str(name or "").strip()
    if PRACTICE_RX.search(text):
        return "practice", ""
    if FORMAT_RX.match(text):
        return "concept", ""
    if LANGUAGE_RX.match(text):
        return "language", ""
    kind = _ontology_kind(text)
    if kind:
        return kind, ""
    if TOOL_RX.search(text) and len(text.split()) <= 4 and text[:1].isupper():
        return "tool", ""
    return "concept", ""


def tag(name, data=None):
    """-> {"kind", "kind_label", "family", "family_label", "category", "source"} for one skill name."""
    data = data or saved()
    k = key_of(name)
    s = data["skills"].get(k)
    fams = families(data)
    if isinstance(s, dict) and s.get("kind") in KINDS:
        kind, fam, source = s["kind"], s.get("family") or "", s.get("source") or "manual"
        if fam and fam not in fams:
            fam = ""
    else:
        kind, fam = rule_tag(name)
        source = "rules"
    if kind not in INTERCHANGEABLE:
        fam = ""
    return {"kind": kind, "kind_label": KINDS[kind], "family": fam, "family_label": family_label(fam, fams),
            "category": skill_categories.category_for(name), "source": source}


class Tagger:
    """Tags many names with one read of the saved file."""

    def __init__(self):
        self.data = saved()
        self.fams = families(self.data)
        self._cache = {}

    def __call__(self, name):
        k = key_of(name)
        if k not in self._cache:
            self._cache[k] = tag(name, self.data)
        return self._cache[k]

    def unit_of(self, key, name):
        """The comparison unit of a skill: its family when it has one, else the skill itself."""
        t = self(name)
        return ("fam:" + t["family"]) if t["family"] else ("skill:" + key)


def family_members(fkey, known_names=()):
    """Every name known to belong to a family: built-in members, saved tags, and any of
    `known_names` (e.g. the skills in the job postings) the tagger puts in it."""
    out = {}
    for fk, _label, _kind, members in FAMILIES:
        if fk == fkey:
            for m in members:
                out.setdefault(key_of(m), m)
    data = saved()
    for k, s in data["skills"].items():
        if isinstance(s, dict) and s.get("family") == fkey:
            out.setdefault(k, s.get("skill") or k)
    if known_names:
        t = Tagger()
        for n in known_names:
            if t(n)["family"] == fkey:
                out.setdefault(key_of(n), n)
    return out


def set_tag(name, kind, family="", source="manual"):
    """Save one skill's tag. family must be a known family key (or "")."""
    if kind not in KINDS:
        raise ValueError("Unknown kind.")
    k = key_of(name)
    if not k:
        raise ValueError("Blank skill name.")

    def fn(data):
        data.setdefault("skills", {})
        data.setdefault("families", {})
        fams = families(data)
        fam = family if (family in fams and kind in INTERCHANGEABLE) else ""
        data["skills"][k] = {"skill": " ".join(str(name).split()), "kind": kind, "family": fam, "source": source}
    store.update("skill_tags", fn)


def clear_tag(name):
    k = key_of(name)
    store.update("skill_tags", lambda data: data.setdefault("skills", {}).pop(k, None))


def add_family(label, kind):
    label = " ".join(str(label or "").split())[:60]
    if not label or kind not in INTERCHANGEABLE:
        raise ValueError("Give the family a name and a kind (language, framework or tool).")
    fkey = "x-" + re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:40]

    def fn(data):
        data.setdefault("families", {})[fkey] = {"label": label, "kind": kind}
    store.update("skill_tags", fn)
    return fkey
