"""
UEnvision — the contents of the Feedback page surveys (SUS, UAT, functional test case sheet):
each survey's purpose, instructions and questions.

Developers can edit them on the Feedback page ("Edit form"); their changes are saved in the
FeedbackForm table and replace the defaults below for everyone. "Back to the original" deletes
the saved copy. Two limits keep the scores right:
  * SUS keeps 6 statements and UAT keeps 10 per audience (the SUS score formula, the UAT
    average and the saved answers q1..qN depend on the count), so only their wording changes.
  * Test cases on the functional sheet can be added, removed, reordered and reworded.
"""
import copy

SUS_COUNT = 6
UAT_COUNT = 10
MAX_TEXT = 1500
MAX_SHORT = 200
MAX_TEST_CASES = 60

DEFAULTS = {
    "sus": {
        "purpose": "to measure how easy UEnvision is to use. The System Usability Scale is a standard "
                   "10-question test that gives UEnvision a usability score from 0 to 100.",
        "instructions": "For each statement, choose how much you agree, from 1 (Strongly disagree), 2 (Disagree), "
                        "3 (Neutral), 4 (Agree) to 5 (Strongly agree).",
        # Statement 1 is worded for who is answering (administrators and developers get the faculty one).
        "first_statements": {
            "student": "I would like to use UEnvision to keep me updated on the skills that job postings ask for, "
                       "so I can prepare for them before I graduate.",
            "alumni": "I would like to use UEnvision to keep me updated on the skills that job postings ask for, "
                      "so I can keep my skills current in my career.",
            "faculty": "I would like to use UEnvision to keep me updated on the skills that job postings ask for, "
                       "so I can include them in the subjects I teach.",
        },
        # Statements 1 to 6 (statement 1 here is only a fallback: first_statements is used).
        "questions": ['I would like to use UEnvision again.',
         'UEnvision is easy to use.',
         'It is easy to navigate through UEnvision.',
         'All parts of UEnvision work well together.',
         'UEnvision looks and works the same way on every page.',
         'I felt confident using UEnvision.'],
    },
    "uat": {
        "purpose": "to check whether UEnvision meets the needs of its users (students, alumni and faculty) and is "
                   "acceptable for use at UE, based on your own experience with it.",
        "instructions": "Tell us how you felt about using UEnvision. For each statement, choose how much you agree, "
                        "from 1 (Strongly disagree), 2 (Disagree), 3 (Neutral), 4 (Agree) to 5 (Strongly agree). "
                        "There are no right or wrong answers.",
        "questions_faculty": ['Overall, I am satisfied with UEnvision.',
         'UEnvision meets my needs for knowing which skills the IT job market asks for.',
         'The dashboard shows the in-demand skills in a way that is clear and easy to understand.',
         'The skill gap analysis helps me see which skills the curriculum should cover more.',
         'The recommendations are useful for improving the subjects I handle.',
         'I trust the results that UEnvision shows.',
         'The look and layout of UEnvision are pleasant.',
         'UEnvision responds quickly when I use it.',
         'I would recommend UEnvision to other faculty members.',
         'I would use UEnvision as part of my work.'],
        "questions_learner": ['Overall, I am satisfied with UEnvision.',
         'UEnvision helps me know which skills IT job postings ask for.',
         'My skill gap page clearly shows which in-demand skills I already have and which I still need.',
         'The job readiness score and skill comparison are easy to understand.',
         'The learning resources suggested for my skill gaps are useful to me.',
         'Answering the survey and updating My subjects & skills is easy.',
         'I trust the results that UEnvision shows.',
         'The look and layout of UEnvision are pleasant.',
         'UEnvision responds quickly when I use it.',
         'I would recommend UEnvision to other students and fresh graduates.'],
    },
    "functional": {
        "purpose": "to confirm that every feature of UEnvision works as it should. Your results show the team which "
                   "parts work and which need fixing.",
        "instructions": "A functional test checks that each part of UEnvision does what it is supposed to do. For each "
                        "test case, do what the scenario says, then answer whether it happened as expected. If it "
                        "didn't, write what happened instead. Comments or remarks about your experience are welcome "
                        "on any test case.",
        "rows": [{'feature': 'Login',
          'scenario': 'You open the UEnvision login page, type the email and password of your account, and click Log '
                      'in. You should be taken straight to your home page (the Dashboard for faculty and '
                      'administrators, My skill gap for students and alumni) with your name shown in the sidebar. If '
                      'you have a Google account with the same email, clicking Continue with Google instead should '
                      'log you in to that same account.'},
         {'feature': 'Dashboard',
          'scenario': 'You open the Dashboard from the sidebar. The stat cards and the Top in-demand skills chart '
                      'should load and show the number of job postings and the most requested skills.'},
         {'feature': 'Dashboard filters',
          'scenario': 'On the Dashboard, you click Filter, set Number of top skills to 5 and Program to BSIT, and '
                      'click Apply filters. The Top in-demand skills chart should update to show 5 skills taken only '
                      'from BSIT-related job postings.'},
         {'feature': 'Skill gap analysis',
          'scenario': 'On the Dashboard, you open the Skill gap analysis tab. The Under-taught and Well-covered '
                      'skill lists should appear, comparing what job postings ask for with what is taught in the '
                      'subjects.'},
         {'feature': 'Recommendations',
          'scenario': 'You open Recommendations from the sidebar and choose one of your subjects. The in-demand '
                      'skills that fit that subject should be listed, each with suggested learning resources.'},
         {'feature': 'Export data',
          'scenario': 'You go to Data, choose a source, and click Export. A CSV file should download containing the '
                      'rows of the table you were viewing.'},
         {'feature': 'Edit settings',
          'scenario': 'You go to Settings, change your name, and click Save. Your new name should be shown right '
                      'away in Settings and in the sidebar.'}],
    },
}
KEYS = tuple(DEFAULTS)


def get(key):
    """The current contents of one survey (the developers' saved copy, or the default)."""
    from .models import FeedbackForm

    content = copy.deepcopy(DEFAULTS[key])
    row = FeedbackForm.objects.filter(key=key).first()
    if row and isinstance(row.content, dict):
        for field, value in row.content.items():
            if field in content:
                content[field] = value
    return content


def get_all():
    from .models import FeedbackForm

    saved = {row.key: row for row in FeedbackForm.objects.filter(key__in=KEYS)}
    out = {}
    for key in KEYS:
        content = copy.deepcopy(DEFAULTS[key])
        row = saved.get(key)
        if row and isinstance(row.content, dict):
            content.update({k: v for k, v in row.content.items() if k in content})
        content["edited"] = bool(row)
        content["updated_at"] = row.updated_at.isoformat() if row else ""
        content["updated_by"] = (row.updated_by.get_full_name() if row and row.updated_by else "")
        out[key] = content
    return out


def _text(value, limit, what):
    text = " ".join(str(value or "").split())
    if not text:
        raise ValueError(f"{what} can't be empty.")
    if len(text) > limit:
        raise ValueError(f"{what} is too long (at most {limit} characters).")
    return text


def _fixed_list(value, count, what):
    if not isinstance(value, list) or len(value) != count:
        raise ValueError(f"{what} must have exactly {count} statements.")
    return [_text(v, MAX_TEXT, f"{what} statement {i + 1}") for i, v in enumerate(value)]


def clean(key, data):
    """Checks a developer's edit and returns what to save, or raises ValueError with a message."""
    if key not in DEFAULTS or not isinstance(data, dict):
        raise ValueError("Unknown form.")
    out = {"purpose": _text(data.get("purpose"), MAX_TEXT, "The purpose"),
           "instructions": _text(data.get("instructions"), MAX_TEXT, "The instructions")}
    if key == "sus":
        firsts = data.get("first_statements")
        if not isinstance(firsts, dict):
            raise ValueError("Statement 1 needs a wording for students, alumni and faculty.")
        out["first_statements"] = {who: _text(firsts.get(who), MAX_TEXT, f"Statement 1 ({who})")
                                   for who in ("student", "alumni", "faculty")}
        out["questions"] = _fixed_list(data.get("questions"), SUS_COUNT, "The SUS")
    elif key == "uat":
        out["questions_faculty"] = _fixed_list(data.get("questions_faculty"), UAT_COUNT, "The faculty UAT")
        out["questions_learner"] = _fixed_list(data.get("questions_learner"), UAT_COUNT, "The student / alumni UAT")
    else:
        rows = data.get("rows")
        if not isinstance(rows, list) or not rows:
            raise ValueError("The test case sheet needs at least one test case.")
        if len(rows) > MAX_TEST_CASES:
            raise ValueError(f"The test case sheet can have at most {MAX_TEST_CASES} test cases.")
        out["rows"] = []
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError("Malformed test case.")
            out["rows"].append({"feature": _text(row.get("feature"), MAX_SHORT, f"Test case {i + 1}'s feature"),
                                "scenario": _text(row.get("scenario"), MAX_TEXT, f"Test case {i + 1}'s scenario")})
    return out
