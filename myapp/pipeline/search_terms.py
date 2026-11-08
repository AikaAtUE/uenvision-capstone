"""
The searches the scraper runs in "Multiple search" mode (and on every automatic run).

The expected job roles of graduates set by CHED Memorandum Order No. 25, s. 2015
(PSG for BSCS, BSIS and BSIT) are always in the list: they can't be edited or removed
on the Data Extraction page, only added to. Each one has a tick box, though, so a run can
leave some of them out: the unticked ones are stored in data/.state/scrape_settings.json
-> skipped_searches (so a role is searched unless someone unticked it). Administrators'
extra searches are stored separately (-> extra_searches) and come after them.
"""

# (program, "primary" | "secondary", roles), as listed in CMO No. 25, s. 2015
CHED_EXPECTED_ROLES = (
    ("BSCS", "primary", (
        "Software Engineer",
        "Systems Software Developer",
        "Research and Development Computing Professional",
        "Applications Software Developer",
        "Computer Programmer",
    )),
    ("BSCS", "secondary", (
        "Systems Analyst",
        "Data Analyst",
        "Quality Assurance Specialist",
        "Software Support Specialist",
    )),
    ("BSIT", "primary", (
        "Web and Applications Developer",
        "Junior Database Administrator",
        "Systems Administrator",
        "Network Engineer",
        "Junior Information Security Administrator",
        "Systems Integration Personnel",
        "IT Audit Assistant",
        "Technical Support Specialist",
    )),
    ("BSIT", "secondary", (
        "QA Specialist",
        "Systems Analyst",
        "Computer Programmer",
    )),
)

MAX_SEARCH_CHARS = 100
MAX_EXTRA_SEARCHES = 50


def clean(text) -> str:
    return " ".join(str(text or "").split())


def default_searches() -> list[dict]:
    """The locked CHED roles, each once, in memorandum order:
    [{"term": ..., "tags": ["BSCS primary", "BSIT secondary"]}, ...]."""
    out, index = [], {}
    for program, level, roles in CHED_EXPECTED_ROLES:
        for role in roles:
            key = role.lower()
            if key not in index:
                index[key] = len(out)
                out.append({"term": role, "tags": []})
            out[index[key]]["tags"].append(f"{program} {level}")
    return out


def default_terms() -> list[str]:
    return [d["term"] for d in default_searches()]


def parse_extra(text) -> tuple[list[str], str | None]:
    """The "add more searches" box: one search per line. Blank lines, repeats and lines
    that are already one of the locked CHED roles are dropped. Returns (searches, error)."""
    locked = {t.lower() for t in default_terms()}
    seen, out = set(), []
    for line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        term = clean(line)
        if not term or term.lower() in locked or term.lower() in seen:
            continue
        if len(term) > MAX_SEARCH_CHARS:
            return out, f"Each search can be up to {MAX_SEARCH_CHARS} characters (“{term[:40]}…” is longer)."
        seen.add(term.lower())
        out.append(term)
    if len(out) > MAX_EXTRA_SEARCHES:
        return out, f"Add up to {MAX_EXTRA_SEARCHES} extra searches."
    return out, None


def parse_skipped(ticked) -> list[str]:
    """The tick boxes of the CHED roles: the roles that were NOT ticked, in memorandum order
    (spelled as in the memorandum, whatever the form sent)."""
    on = {clean(t).lower() for t in ticked or []}
    return [t for t in default_terms() if t.lower() not in on]


def ticked_terms(skipped=None) -> list[str]:
    """The CHED roles a multiple-search run searches: every one that wasn't unticked."""
    off = {clean(t).lower() for t in skipped or []}
    return [t for t in default_terms() if t.lower() not in off]


def multiple_list(extra, skipped=None) -> list[str]:
    """Every search of a multiple-search run: the ticked CHED roles first, then the extras."""
    out = ticked_terms(skipped)
    have = {t.lower() for t in default_terms()}       # an extra never brings back an unticked role
    for term in (clean(x) for x in extra or []):
        if term and term.lower() not in have:
            have.add(term.lower())
            out.append(term)
    return out
