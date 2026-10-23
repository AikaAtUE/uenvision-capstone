"""
UEnvision — curriculum catalog + time-aware term logic for the Student / Alumni /
Professor curriculum-mapping surveys.

############################################################################
# IMPORTANT — PLACEHOLDER CURRICULUM DATA
#
# The exact BSIT and BSCS curricula (subject codes/names/units per term) and
# the exact AY2026-2027 school-calendar dates were pasted earlier in our
# conversation, but that message fell outside the context window that
# carried over here, so I no longer have the literal text to copy from.
#
# Everything below is wired up and fully working, but the actual subject
# codes/names are realistic SAMPLE/PLACEHOLDER data, not your official
# curriculum. Re-paste the exact BSIT/BSCS curriculum tables (and the exact
# calendar, if you want the semester switch below to be date-driven instead
# of the current fixed flag) and I will drop the real subjects in — the
# structure (SUBJECTS / TERM_SEQUENCE) is designed so that's a pure data
# swap, no logic changes needed.
#
# Flip this to False once the real curriculum is in place, so the
# "sample data" banner stops showing on the survey pages.
############################################################################
"""

CURRICULUM_IS_PLACEHOLDER = True

BSIT = "BSIT"
BSCS = "BSCS"
PROGRAMS = [BSIT, BSCS]
PROGRAM_LABELS = {BSIT: "BS Information Technology", BSCS: "BS Computer Science"}

# ---------------------------------------------------------------------------
# Which real-world academic period is "current" right now.
#
# Today is within First Semester AY 2026-2027. This is a fixed flag rather
# than something computed from exact calendar dates, because the exact
# calendar text is the other piece of data lost in the context handoff
# above. Update this each term (or send me the exact calendar dates and
# I'll make it switch automatically based on today's date).
# ---------------------------------------------------------------------------
CURRENT_AY = "2026-2027"
CURRENT_SEM_SLOT = "1"  # "1" = 1st Semester, "2" = 2nd Semester, "summer" = Summer
CURRENT_SEM_LABEL = f"1st Semester AY {CURRENT_AY}"
PREVIOUS_SEM_LABEL = f"2nd Semester AY 2025-2026"
PREVIOUS_SUMMER_LABEL = "Summer 2026"

# ---------------------------------------------------------------------------
# Term sequence per program (in chronological order). Each program places its
# single Summer/Practicum block at a different point, which is exactly why
# "previous semester" can't be computed the same way for both programs.
# ---------------------------------------------------------------------------
TERM_SEQUENCE = {
    BSIT: [
        {"key": "y1s1", "year": 1, "slot": "1", "label": "1st Year – 1st Semester"},
        {"key": "y1s2", "year": 1, "slot": "2", "label": "1st Year – 2nd Semester"},
        {"key": "y2s1", "year": 2, "slot": "1", "label": "2nd Year – 1st Semester"},
        {"key": "y2s2", "year": 2, "slot": "2", "label": "2nd Year – 2nd Semester"},
        {"key": "y2sum", "year": 2, "slot": "summer", "label": "2nd Year – Summer"},
        {"key": "y3s1", "year": 3, "slot": "1", "label": "3rd Year – 1st Semester"},
        {"key": "y3s2", "year": 3, "slot": "2", "label": "3rd Year – 2nd Semester"},
        {"key": "y4s1", "year": 4, "slot": "1", "label": "4th Year – 1st Semester"},
        {"key": "y4s2", "year": 4, "slot": "2", "label": "4th Year – 2nd Semester (Practicum)"},
    ],
    BSCS: [
        {"key": "y1s1", "year": 1, "slot": "1", "label": "1st Year – 1st Semester"},
        {"key": "y1s2", "year": 1, "slot": "2", "label": "1st Year – 2nd Semester"},
        {"key": "y2s1", "year": 2, "slot": "1", "label": "2nd Year – 1st Semester"},
        {"key": "y2s2", "year": 2, "slot": "2", "label": "2nd Year – 2nd Semester"},
        {"key": "y3s1", "year": 3, "slot": "1", "label": "3rd Year – 1st Semester"},
        {"key": "y3s2", "year": 3, "slot": "2", "label": "3rd Year – 2nd Semester"},
        {"key": "y3sum", "year": 3, "slot": "summer", "label": "3rd Year – Summer (Practicum)"},
        {"key": "y4s1", "year": 4, "slot": "1", "label": "4th Year – 1st Semester"},
        {"key": "y4s2", "year": 4, "slot": "2", "label": "4th Year – 2nd Semester"},
    ],
}

# ---------------------------------------------------------------------------
# SAMPLE subject catalog (see the placeholder notice at the top of this file).
# Only the technical/major subjects are listed — general-education subjects
# (math, humanities, PE, NSTP, etc.) don't carry technical skills to survey,
# so they're left out of the picker on purpose.
# ---------------------------------------------------------------------------
SUBJECTS = {
    BSIT: {
        "y1s1": [
            {"code": "IT111", "name": "Introduction to Computing", "units": 3},
            {"code": "IT112", "name": "Computer Programming 1", "units": 3},
            {"code": "IT113", "name": "Fundamentals of Database Systems", "units": 3},
        ],
        "y1s2": [
            {"code": "IT121", "name": "Computer Programming 2", "units": 3},
            {"code": "IT122", "name": "Data Structures and Algorithms", "units": 3},
            {"code": "IT123", "name": "Web Systems and Technologies", "units": 3},
        ],
        "y2s1": [
            {"code": "IT211", "name": "Information Management", "units": 3},
            {"code": "IT212", "name": "Platform Technologies", "units": 3},
            {"code": "IT213", "name": "Integrative Programming and Technologies", "units": 3},
        ],
        "y2s2": [
            {"code": "IT221", "name": "Networking 1 (Fundamentals)", "units": 3},
            {"code": "IT222", "name": "Human Computer Interaction", "units": 3},
            {"code": "IT223", "name": "Applications Development and Emerging Technologies", "units": 3},
        ],
        "y2sum": [
            {"code": "IT231", "name": "Systems Integration and Architecture 1", "units": 3},
        ],
        "y3s1": [
            {"code": "IT311", "name": "Systems Integration and Architecture 2", "units": 3},
            {"code": "IT312", "name": "Networking 2", "units": 3},
            {"code": "IT313", "name": "Information Assurance and Security 1", "units": 3},
        ],
        "y3s2": [
            {"code": "IT321", "name": "Information Assurance and Security 2", "units": 3},
            {"code": "IT322", "name": "Capstone Project 1", "units": 3},
            {"code": "IT323", "name": "System Administration and Maintenance", "units": 3},
        ],
        "y4s1": [
            {"code": "IT411", "name": "Capstone Project 2", "units": 3},
            {"code": "IT412", "name": "IT Elective 1 — Mobile Application Development", "units": 3},
            {"code": "IT413", "name": "IT Elective 2 — Cloud Computing", "units": 3},
        ],
        "y4s2": [
            {"code": "CPR4970", "name": "Practicum (On-the-Job Training)", "units": 6},
        ],
    },
    BSCS: {
        "y1s1": [
            {"code": "CS111", "name": "Introduction to Computing", "units": 3},
            {"code": "CS112", "name": "Computer Programming 1", "units": 3},
            {"code": "CS113", "name": "Discrete Structures 1", "units": 3},
        ],
        "y1s2": [
            {"code": "CS121", "name": "Computer Programming 2", "units": 3},
            {"code": "CS122", "name": "Data Structures and Algorithms", "units": 3},
            {"code": "CS123", "name": "Discrete Structures 2", "units": 3},
        ],
        "y2s1": [
            {"code": "CS211", "name": "Object-Oriented Programming", "units": 3},
            {"code": "CS212", "name": "Database Management Systems", "units": 3},
            {"code": "CS213", "name": "Computer Organization and Architecture", "units": 3},
        ],
        "y2s2": [
            {"code": "CS221", "name": "Operating Systems", "units": 3},
            {"code": "CS222", "name": "Design and Analysis of Algorithms", "units": 3},
            {"code": "CS223", "name": "Web Development", "units": 3},
        ],
        "y3s1": [
            {"code": "CS311", "name": "Automata Theory and Formal Languages", "units": 3},
            {"code": "CS312", "name": "Software Engineering", "units": 3},
            {"code": "CS313", "name": "Artificial Intelligence", "units": 3},
        ],
        "y3s2": [
            {"code": "CS321", "name": "Machine Learning", "units": 3},
            {"code": "CS322", "name": "Human Computer Interaction", "units": 3},
            {"code": "CS323", "name": "Information Assurance and Security", "units": 3},
        ],
        "y3sum": [
            {"code": "CCS4970", "name": "Practicum (On-the-Job Training)", "units": 6},
        ],
        "y4s1": [
            {"code": "CS411", "name": "Thesis / Capstone 1", "units": 3},
            {"code": "CS412", "name": "CS Elective 1 — Data Analytics", "units": 3},
            {"code": "CS413", "name": "CS Elective 2 — Mobile Computing", "units": 3},
        ],
        "y4s2": [
            {"code": "CS421", "name": "Thesis / Capstone 2", "units": 3},
            {"code": "CS422", "name": "CS Elective 3 — Cloud Computing", "units": 3},
        ],
    },
}

YEAR_LEVELS = [1, 2, 3, 4]


def term_sequence(program):
    return TERM_SEQUENCE.get(program, [])


def term_by_key(program, key):
    for t in term_sequence(program):
        if t["key"] == key:
            return t
    return None


def subjects_for_term(program, key):
    return SUBJECTS.get(program, {}).get(key, [])


def all_terms_flat():
    """All (program, term) pairs — used by the alumni 'which semester was your
    last one' picker, which isn't locked to a fixed year/eligibility rule."""
    out = []
    for program in PROGRAMS:
        for term in term_sequence(program):
            out.append({"program": program, **term})
    return out


def all_subjects_flat():
    """Every subject across both curricula, each tagged with its program/term —
    used once to precompute ontology skill suggestions for the whole catalog."""
    out = []
    for program in PROGRAMS:
        for term in term_sequence(program):
            for subj in subjects_for_term(program, term["key"]):
                out.append({"program": program, "term_key": term["key"], "term_label": term["label"], **subj})
    return out


def student_eligible_terms(program, year_level):
    """
    My own derived interpretation of "since it's first semester, 1st years and
    4th years will not be able to answer the second semester" — please correct
    me if this isn't what your team meant:

    Right now (1st Semester AY2026-2027), a student in year level N is
    currently taking that year's 1st-semester subjects (yNs1) — that's their
    "current semester", required. Their "previous semester" (optional) is
    whatever term immediately precedes yNs1 in THEIR program's actual
    sequence — which is why this is program-aware: a BSIT 3rd year's previous
    term is their 2nd-year Summer block, while a BSCS 3rd year's previous
    term is their 2nd Year/2nd Semester (BSCS has no Summer block until after
    3rd year). A 1st year has no previous term at all yet. Nobody — 1st year
    or 4th year — is offered "the 2nd semester" of their current year, since
    that hasn't happened yet this academic year; that falls out automatically
    here rather than needing a special case.

    Returns (current_term, previous_term_or_None), or (None, None) if the
    program/year combination doesn't exist.
    """
    seq = term_sequence(program)
    current_key = f"y{year_level}s1"
    idx = next((i for i, t in enumerate(seq) if t["key"] == current_key), None)
    if idx is None:
        return None, None
    current_term = seq[idx]
    previous_term = seq[idx - 1] if idx > 0 else None
    return current_term, previous_term


def build_student_eligibility():
    """{program: {str(year): {"current": {...}, "previous": {...} or None}}} — the
    full, ready-to-serialize structure the student survey page needs, with
    subjects embedded so the front-end doesn't need a second lookup."""
    out = {}
    for program in PROGRAMS:
        out[program] = {}
        for year in YEAR_LEVELS:
            current_term, previous_term = student_eligible_terms(program, year)
            if current_term is None:
                continue
            out[program][str(year)] = {
                "current": {
                    "term_key": current_term["key"],
                    "term_label": current_term["label"],
                    "subjects": subjects_for_term(program, current_term["key"]),
                },
                "previous": None if previous_term is None else {
                    "term_key": previous_term["key"],
                    "term_label": previous_term["label"],
                    "subjects": subjects_for_term(program, previous_term["key"]),
                },
            }
    return out


def professor_term_pools():
    """
    Professors aren't locked to one year level — in the real world, "1st
    Semester AY2026-2027" is happening for every year level at once, across
    both programs. So their "current semester" pool is every subject slotted
    into a 1st-semester term (any year, either program); their "previous
    semester" pool is every subject slotted into a 2nd-semester term (the
    just-finished AY2025-2026); and, since it's the most recent past term,
    "previous summer" covers whichever program's Summer/Practicum block just
    happened.

    Returns {"current": [...], "previous_semester": [...], "previous_summer": [...]}
    each a list of subjects tagged with program + term label, deduplicated by
    (program, code).
    """
    pools = {"current": [], "previous_semester": [], "previous_summer": []}
    seen = set()
    for program in PROGRAMS:
        for term in term_sequence(program):
            bucket = {"1": "current", "2": "previous_semester", "summer": "previous_summer"}.get(term["slot"])
            if not bucket:
                continue
            for subj in subjects_for_term(program, term["key"]):
                dedup_key = (program, subj["code"])
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                pools[bucket].append({"program": program, "term_key": term["key"], "term_label": term["label"], **subj})
    return pools
