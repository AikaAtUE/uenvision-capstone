"""
UEnvision — curriculum catalog + time-aware term logic for the Student / Alumni /
Professor curriculum-mapping surveys.

SUBJECTS below is the official UE-CCSS BSIT and BSCS curriculum. Only the
computing / program subjects are listed: General Education (ZGE, ZPD),
Physical Education (PPE) and NSTP (MLC) subjects don't carry technical skills
to survey, so they're left out of the picker on purpose. Professional
Electives, Capstone/Thesis, and Practicum ARE listed.

Which semester is "current" is worked out from today's date against
ACADEMIC_TERMS (the AY 2026-2027 school calendar). Add the next academic year's
terms to ACADEMIC_TERMS when its calendar comes out. After the last listed term
starts, that term simply stays "current".
"""
import re
from datetime import date

from django.utils import timezone

# Kept for the templates' "sample curriculum" banner; the real curriculum is in.
CURRICULUM_IS_PLACEHOLDER = False

BSIT = "BSIT"
BSCS = "BSCS"
PROGRAMS = [BSIT, BSCS]
PROGRAM_LABELS = {BSIT: "BS Information Technology", BSCS: "BS Computer Science"}

# ---------------------------------------------------------------------------
# School calendar (Manila campus, CCSS). Each term starts on its first day of
# regular classes. "slot" is "1" (1st Semester), "2" (2nd Semester) or "summer".
# ---------------------------------------------------------------------------
ACADEMIC_TERMS = [
    # Start date not in the pasted calendar; this entry only serves as the
    # "previous semester" of Summer 2026 / 1st Semester AY 2026-2027.
    {"slot": "2", "ay": "2025-2026", "label": "2nd Semester AY 2025-2026", "start": date(2026, 1, 8)},
    {"slot": "summer", "ay": "2025-2026", "label": "Summer 2026", "start": date(2026, 5, 20)},
    {"slot": "1", "ay": "2026-2027", "label": "1st Semester AY 2026-2027", "start": date(2026, 7, 23)},
    {"slot": "2", "ay": "2026-2027", "label": "2nd Semester AY 2026-2027", "start": date(2027, 1, 8)},
]


def _today(today=None):
    return today or timezone.localdate()


def current_period(today=None):
    """The academic period in effect today:
    {"slot", "ay", "current_label", "previous_sem_label", "previous_summer_label"}.
    previous_summer_label is only set during a 1st Semester (the summer that just
    ended); otherwise it's None."""
    today = _today(today)
    terms = sorted(ACADEMIC_TERMS, key=lambda t: t["start"])
    idx = 0
    for i, t in enumerate(terms):
        if t["start"] <= today:
            idx = i
    current = terms[idx]
    earlier = terms[:idx]
    previous_sem = next((t for t in reversed(earlier) if t["slot"] != "summer"), None)
    previous_summer = None
    if current["slot"] == "1" and earlier and earlier[-1]["slot"] == "summer":
        previous_summer = earlier[-1]
    return {
        "slot": current["slot"],
        "ay": current["ay"],
        "current_label": current["label"],
        "previous_sem_label": previous_sem["label"] if previous_sem else None,
        "previous_summer_label": previous_summer["label"] if previous_summer else None,
    }


# ---------------------------------------------------------------------------
# Term sequence per program (in chronological order). Each program places its
# single Summer block at a different point, which is exactly why "previous
# semester" can't be computed the same way for both programs.
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


def _s(code, name, units=3):
    return {"code": code, "name": name, "units": units}


SUBJECTS = {
    BSIT: {
        "y1s1": [
            _s("CCP 1101", "Computer Programming 1"),
            _s("CIC 1101", "Introduction to Computing"),
            _s("CSP 1101", "Social and Professional Issues in Computing"),
        ],
        "y1s2": [
            _s("CCP 1102", "Computer Programming 2"),
            _s("CDS 1101", "Data Structures and Algorithms"),
            _s("CFD 1101", "Fundamentals of Database Systems"),
        ],
        "y2s1": [
            _s("CBM 1101", "Business Process Management"),
            _s("CCP 1103", "Computer Programming 3"),
            _s("CDE 1101", "Applications Development and Emerging Technologies"),
            _s("CDM 1101", "Discrete Mathematics for ITE"),
            _s("CIM 1101", "Information Management"),
            _s("CIT 2101", "Application of Statistics in IT"),
            _s("CIT 2102", "Hardware, Software, and Peripherals"),
        ],
        "y2s2": [
            _s("CDT 1101", "Data Analytics"),
            _s("CHC 1101", "Human Computer Interaction"),
            _s("CIA 1101", "Information Assurance and Security 1"),
            _s("CIP 1101", "Integrative Programming and Technologies 1"),
            _s("CIT 2201", "Networking 1"),
            _s("CSA 1101", "Systems Analysis, Design and Prototyping"),
        ],
        "y2sum": [
            _s("CIP 1102", "Integrative Programming and Technologies 2"),
            _s("CIT 2301", "Platform Technologies"),
        ],
        "y3s1": [
            _s("CIA 1102", "Information Assurance and Security 2"),
            _s("CIT 3101", "Networking 2"),
            _s("CIT 3102", "Systems Integration and Architecture"),
            _s("CIT EL01", "Professional Elective 1"),
            _s("CMR 1101", "Methods of Research for IT/IS"),
            _s("CMS 1101", "Multimedia Systems"),
        ],
        "y3s2": [
            _s("CIT 3201", "Networking 3"),
            _s("CIT EL02", "Professional Elective 2"),
            _s("CNA 1101", "Numerical Analysis for ITE"),
            _s("CPP 4980", "Capstone Project and Research 1"),
        ],
        "y4s1": [
            _s("CIT 4101", "Certification Course"),
            _s("CIT 4102", "Systems Administration and Maintenance"),
            _s("CIT EL03", "Professional Elective 3"),
            _s("CIT EL04", "Professional Elective 4"),
            _s("CPD 4990", "Capstone Project and Research 2"),
            _s("CQM 1101", "Quantitative Methods (including Modeling and Simulation)"),
        ],
        "y4s2": [
            _s("CPR 4970", "Practicum for IT/IS", 6),
        ],
    },
    BSCS: {
        "y1s1": [
            _s("CCS 1101", "Fundamentals of Programming"),
            _s("CIC 1101", "Introduction to Computing"),
        ],
        "y1s2": [
            _s("CCS 1201", "Intermediate Programming"),
            _s("CMA 1101", "Analysis 1 for CS"),
            _s("CSP 1101", "Social and Professional Issues in Computing"),
        ],
        "y2s1": [
            _s("CCS 2101", "Discrete Structures 1"),
            _s("CCS 2102", "Object-Oriented Programming"),
            _s("CDS 1101", "Data Structures and Algorithms"),
            _s("CHC 1101", "Human Computer Interaction"),
            _s("CIM 1101", "Information Management"),
            _s("CMA 1102", "Analysis 2 for CS"),
        ],
        "y2s2": [
            _s("CCS 2201", "Architecture and Organization"),
            _s("CCS 2202", "Discrete Structures 2"),
            _s("CCS 2203", "Operating Systems"),
            _s("CCS 2204", "Statistics for CS"),
            _s("CIA 1101", "Information Assurance and Security 1"),
            _s("CIP 1101", "Integrative Programming and Technologies 1"),
            _s("CSE 1101", "Software Engineering 1"),
        ],
        "y3s1": [
            _s("APC 3101", "Physics for CS (with Electromagnetism)", 4),
            _s("CCS 3101", "Algorithm and Complexity"),
            _s("CCS 3102", "Methods of Research for CS"),
            _s("CCS 3103", "Networks and Communications"),
            _s("CCS 3104", "Software Engineering 2"),
            _s("CDT 1101", "Data Analytics"),
            _s("CMS 1101", "Multimedia Systems"),
        ],
        "y3s2": [
            _s("CCS 3201", "Artificial Intelligence"),
            _s("CCS 3202", "Automata Theory and Formal Languages"),
            _s("CCS 4980", "Thesis Writing 1 for CS"),
            _s("CCS EL01", "Professional Elective 1"),
            _s("CDE 1101", "Applications Development and Emerging Technologies"),
        ],
        "y3sum": [
            _s("CCS 4970", "Practicum for CS"),
        ],
        "y4s1": [
            _s("CCS 4101", "Modeling and Simulation"),
            _s("CCS 4102", "Programming Languages"),
            _s("CCS 4990", "Thesis Writing 2 for CS"),
            _s("CCS EL02", "Professional Elective 2"),
            _s("CNA 1101", "Numerical Analysis for ITE"),
        ],
        "y4s2": [
            _s("CCS 4201", "Digital Electronics and Logic Design"),
            _s("CCS EL03", "Professional Elective 3"),
            _s("CCS EL04", "Professional Elective 4"),
            _s("CIS 3202", "Technopreneurship"),
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


def subject_lookup():
    """{(program, code): {"name", "term_key", "term_label", "year"}} for every subject."""
    out = {}
    for program in PROGRAMS:
        for term in term_sequence(program):
            for subj in subjects_for_term(program, term["key"]):
                out[(program, subj["code"])] = {
                    "name": subj["name"], "term_key": term["key"],
                    "term_label": term["label"], "year": term["year"],
                }
    return out


# Practicum/OJT, Methods of Research and Capstone/Thesis subjects are student
# projects that professors advise rather than teach, so they're left out of the
# Professor Survey and the professors' per-subject recommendations. Students
# and alumni can still report skills for them.
NOT_TAUGHT_BY_PROFESSORS = {
    "CPR 4970",   # Practicum for IT/IS
    "CCS 4970",   # Practicum for CS
    "CMR 1101",   # Methods of Research for IT/IS
    "CCS 3102",   # Methods of Research for CS
    "CPP 4980",   # Capstone Project and Research 1
    "CPD 4990",   # Capstone Project and Research 2
    "CCS 4980",   # Thesis Writing 1 for CS
    "CCS 4990",   # Thesis Writing 2 for CS
}

# "Professional Elective 1-4" are placeholders: each one is a different subject
# depending on the elective track, so professors add the elective they actually
# teach as a subject of their own (see clean_custom_subject) instead.
PROFESSIONAL_ELECTIVES = {
    "CIT EL01", "CIT EL02", "CIT EL03", "CIT EL04",
    "CCS EL01", "CCS EL02", "CCS EL03", "CCS EL04",
}

# Everything left out of the professors' subject lists.
HIDDEN_FROM_PROFESSORS = NOT_TAUGHT_BY_PROFESSORS | PROFESSIONAL_ELECTIVES

_CUSTOM_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9 \-]{1,19}$")


def clean_custom_subject(entry):
    """A subject a professor added because it isn't in the list (an elective, a
    service subject, ...). -> ({"code", "name", "programs", "custom": True}, None)
    or (None, error message). It must have BSIT and/or BSCS students, and its code
    can't be one that's already in the curriculum."""
    if not isinstance(entry, dict):
        return None, "Malformed subject entry."
    code = " ".join(str(entry.get("code") or "").upper().split())
    name = " ".join(str(entry.get("name") or "").split())
    if not _CUSTOM_CODE_RE.match(code):
        return None, "Give the added subject a subject code, e.g. CIT 4101."
    if not 2 <= len(name) <= 120:
        return None, f"Give {code} a subject title."
    if code in subject_by_code():
        return None, f"{code} is already in the subject list."
    programs = entry.get("programs")
    if not isinstance(programs, list) or not programs or any(p not in PROGRAMS for p in programs):
        return None, f"{code} must have BSIT or BSCS students to be included."
    return {"code": code, "name": name, "programs": [p for p in PROGRAMS if p in programs], "custom": True}, None


def subject_by_code():
    """{code: {"name", "programs": [...], "term_label"}} -- one entry per subject
    code. BSIT and BSCS share some subjects (same code, same name, sometimes in a
    different year); a shared code is one subject everywhere in the app."""
    out = {}
    for program in PROGRAMS:
        for term in term_sequence(program):
            for subj in subjects_for_term(program, term["key"]):
                entry = out.setdefault(subj["code"], {"name": subj["name"], "programs": [],
                                                      "term_label": term["label"]})
                if program not in entry["programs"]:
                    entry["programs"].append(program)
    return out


_SLOT_DIGIT = {"1": "1", "2": "2", "summer": "3"}
_PROGRAM_SUFFIX = {BSIT: "IT", BSCS: "CS"}


def subject_term_tags():
    """{code: [{"tag": "Y1S1IT", "program", "year"}]} -- where each subject sits in
    each curriculum: year, semester (1, 2, or 3 for summer) and program. A subject
    both programs share gets one tag per program."""
    out = {}
    for program in PROGRAMS:
        for term in term_sequence(program):
            tag = f"Y{term['year']}S{_SLOT_DIGIT[term['slot']]}{_PROGRAM_SUFFIX[program]}"
            for subj in subjects_for_term(program, term["key"]):
                out.setdefault(subj["code"], []).append({"tag": tag, "program": program, "year": term["year"],
                                                         "sem": int(_SLOT_DIGIT[term["slot"]])})
    return out


def subject_sort_key(code, tags=None):
    """Year -> semester -> course order for a subject. A subject both programs share
    is placed where BSIT has it (BSIT first). Unknown codes go last."""
    tags = (tags if tags is not None else subject_term_tags()).get(code) or []
    if not tags:
        return (99, 9, 9, code)
    first = min(tags, key=lambda t: (PROGRAMS.index(t["program"]), t["year"], t["sem"]))
    return (first["year"], first["sem"], PROGRAMS.index(first["program"]), code)


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


def student_eligible_terms(program, year_level, slot=None):
    """
    A student in year level N during a given semester slot is taking that
    year's term for the slot (yNs1 / yNs2 / yNsum) — that's their "current
    semester", required. Their "previous semester" (also required) is the
    regular semester (1st or 2nd) that comes right before it in THEIR program's
    sequence, never a Summer. If their program has a Summer term between that
    semester and now, it's included too ("previous_summer"): during the 1st
    Semester a BSIT 3rd year reports 2nd Year/2nd Semester plus their 2nd-year
    Summer, while a BSCS 3rd year only reports 2nd Year/2nd Semester. Every term
    before the previous semester is offered as optional ("earlier").

    Nobody is offered a term that hasn't happened yet, so during the 1st
    Semester 1st and 4th years (and everyone else) can't answer for their
    current year's 2nd Semester. During Summer, a student whose program has no
    summer term in their year reports the 2nd Semester they just finished.

    Returns (current_term, previous_term_or_None, previous_summer_terms,
    earlier_terms), or (None, None, [], []) if the program/year combination
    doesn't exist.
    """
    slot = slot or current_period()["slot"]
    seq = term_sequence(program)
    keys = [t["key"] for t in seq]
    current_key = f"y{year_level}sum" if slot == "summer" else f"y{year_level}s{slot}"
    if current_key not in keys and slot == "summer":
        current_key = f"y{year_level}s2"
    if current_key not in keys:
        return None, None, [], []
    idx = keys.index(current_key)
    prev_idx = idx - 1
    while prev_idx >= 0 and seq[prev_idx]["slot"] == "summer":
        prev_idx -= 1
    if prev_idx < 0:
        return seq[idx], None, [], []
    return seq[idx], seq[prev_idx], seq[prev_idx + 1:idx], seq[:prev_idx]


def _term_payload(program, term):
    return {
        "term_key": term["key"],
        "term_label": term["label"],
        "subjects": subjects_for_term(program, term["key"]),
    }


def build_student_eligibility(slot=None):
    """{program: {str(year): {"current": {...}, "previous": {...} or None,
    "previous_summer": [...], "earlier": [...]}}}
    — the full, ready-to-serialize structure the student survey page needs, with
    subjects embedded so the front-end doesn't need a second lookup."""
    slot = slot or current_period()["slot"]
    out = {}
    for program in PROGRAMS:
        out[program] = {}
        for year in YEAR_LEVELS:
            current_term, previous_term, previous_summer, earlier = student_eligible_terms(program, year, slot)
            if current_term is None:
                continue
            out[program][str(year)] = {
                "current": _term_payload(program, current_term),
                "previous": None if previous_term is None else _term_payload(program, previous_term),
                "previous_summer": [_term_payload(program, t) for t in previous_summer],
                "earlier": [_term_payload(program, t) for t in earlier],
            }
    return out


def professor_term_pools(slot=None):
    """
    Professors aren't locked to one year level — a semester is happening for
    every year level at once, across both programs. So their "current semester"
    pool is every subject slotted into a term of the current slot (any year,
    either program); their "previous semester" pool is every subject of the
    other regular semester; and during a 1st Semester, "previous summer" covers
    the Summer block that just ended. During Summer, "current" is the summer
    subjects and "previous semester" is the 2nd Semester.

    Returns {"current": [...], "previous_semester": [...], "previous_summer": [...]}
    each a list of subjects tagged with the programs that have them + term label,
    deduplicated by subject code (a subject shared by BSIT and BSCS appears once,
    in the most recent pool either program schedules it in).
    """
    slot = slot or current_period()["slot"]
    buckets = {
        "1": {"1": "current", "2": "previous_semester", "summer": "previous_summer"},
        "2": {"2": "current", "1": "previous_semester"},
        "summer": {"summer": "current", "2": "previous_semester"},
    }[slot]
    order = ["current", "previous_semester", "previous_summer"]
    by_code = {}
    for program in PROGRAMS:
        for term in term_sequence(program):
            bucket = buckets.get(term["slot"])
            if not bucket:
                continue
            for subj in subjects_for_term(program, term["key"]):
                if subj["code"] in HIDDEN_FROM_PROFESSORS:
                    continue
                entry = by_code.get(subj["code"])
                if entry is None:
                    by_code[subj["code"]] = entry = {"bucket": bucket, "programs": [],
                                                     "term_key": term["key"], "term_label": term["label"], **subj}
                elif order.index(bucket) < order.index(entry["bucket"]):
                    entry.update(bucket=bucket, term_key=term["key"], term_label=term["label"])
                if program not in entry["programs"]:
                    entry["programs"].append(program)
    pools = {name: [] for name in order}
    for entry in by_code.values():
        pools[entry.pop("bucket")].append(entry)
    tags = subject_term_tags()
    for pool in pools.values():
        pool.sort(key=lambda e: subject_sort_key(e["code"], tags))
    return pools
