import json


from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from ..models import SurveyResponse
from .. import feedback_nudge
from .common import PH_TIME


@login_required
def feedback_view(request):
    audience = sus_audience(request.user)
    return render(request, "feedback.html", {"active_page": "feedback",
                                             "sus_first_statement": SUS_FIRST_STATEMENTS[audience],
                                             "uat_audience": uat_audience(request.user)})


@login_required
@require_POST
def feedback_later_view(request):
    """The banner's "Later" button: hide it for a few days, then go back to the same page."""
    feedback_nudge.snooze(request.user)
    nxt = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        nxt = reverse("student_dashboard" if request.user.is_learner else "dashboard")
    return redirect(nxt)


# ---------------------------------------------------------------------------
# Feedback surveys (SUS / UAT / functional test sheet) — called by survey.js
# ---------------------------------------------------------------------------
MAX_SURVEY_ROWS = 200


# 3 = the 6-statement, all-positive, plain-English SUS (every item scores answer - 1).
# Responses saved before it used the 10-item SUS (no "sus_version" = standard alternating,
# 2 = all-positive), so keep the versions apart when averaging.
# 4 = same scoring as 3, but the statement set changed (navigation and consistency
#     replaced "without a technical person" and "most people would learn quickly").
# 5 = same scoring as 4, but statement 1 ("I would like to use UEnvision again.") became
#     "I would like to use UEnvision to ...", worded for students, alumni or faculty
#     (see SUS_FIRST_STATEMENTS; each response saves which one it was shown as "sus_audience").
SUS_VERSION = 5
SUS_QUESTION_COUNT = 6  # must match SUS_QUESTIONS in survey.js

# UAT 2 = ten Likert statements (1-5) about satisfaction and how UEnvision felt to use,
# saved as q1..q10 with uat_score = their average. Older UAT responses (no "uat_version")
# were Yes/No checks of each feature (login_worked, dashboard_worked, ...), which the
# Functional test case sheet now covers.
UAT_VERSION = 2
UAT_QUESTION_COUNT = 10  # must match UAT_QUESTIONS and UAT_QUESTIONS_STUDENT in survey.js
# Students and alumni answer their own UAT: the same ten-statement Likert form and scoring,
# with statements about their side of UEnvision (My skill gap, learning resources, their
# survey) instead of the faculty pages. Each response saves which set it was shown as
# "uat_audience" ("learner" or "faculty"), so the two are kept apart when averaging.
UAT_AUDIENCES = ("learner", "faculty")


# Statement 1 depends on who is answering. Administrators and developers get the faculty
# wording, since they use the same staff pages.
SUS_FIRST_STATEMENTS = {
    "student": "I would like to use UEnvision to keep me updated on the skills that job postings ask for, "
               "so I can prepare for them before I graduate.",
    "alumni": "I would like to use UEnvision to keep me updated on the skills that job postings ask for, "
              "so I can keep my skills current in my career.",
    "faculty": "I would like to use UEnvision to keep me updated on the skills that job postings ask for, "
               "so I can include them in the subjects I teach.",
}


def sus_audience(user):
    """Which wording of SUS statement 1 this account sees: student, alumni or faculty."""
    if user.role == user.Role.STUDENT:
        return "student"
    if user.role == user.Role.ALUMNI:
        return "alumni"
    return "faculty"


def uat_audience(user):
    """Which UAT statement set this account answers: "learner" (students and alumni) or
    "faculty" (faculty, administrators and developers)."""
    return "learner" if user.is_learner else "faculty"


def _compute_sus_score(answers):
    """All-positive SUS: every item scores (answer - 1), scaled to 0-100."""
    return round(sum(a - 1 for a in answers) / (4 * len(answers)) * 100, 2)


@require_POST
def survey_submit_view(request):
    # Return JSON (not a redirect) so the fetch() in survey.js sees a real 401.
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "error": "Please log in again."}, status=401)

    try:
        body = json.loads(request.body)
        kind = body["type"]
        rows = body["rows"]
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"ok": False, "error": "Malformed request."}, status=400)

    valid_types = {value for value, _ in SurveyResponse.SURVEY_TYPES}
    if (
        kind not in valid_types
        or not isinstance(rows, list)
        or not 1 <= len(rows) <= MAX_SURVEY_ROWS
        or not all(isinstance(r, dict) for r in rows)
    ):
        return JsonResponse({"ok": False, "error": "Invalid survey data."}, status=400)
    if request.user.is_learner and kind == SurveyResponse.FUNCTIONAL:
        return JsonResponse({"ok": False, "error": "Students and alumni answer the SUS and UAT surveys only."}, status=403)

    if kind == SurveyResponse.SUS:
        for row in rows:
            answers = [row.get(f"q{n}") for n in range(1, SUS_QUESTION_COUNT + 1)]
            if not all(isinstance(a, int) and not isinstance(a, bool) and 1 <= a <= 5 for a in answers):
                return JsonResponse({"ok": False, "error": "SUS answers must be 1-5."}, status=400)
            row["sus_score"] = _compute_sus_score(answers)  # never trust the client's score
            row["sus_version"] = SUS_VERSION
            row["sus_audience"] = sus_audience(request.user)  # which statement 1 they were shown

    if kind == SurveyResponse.UAT:
        for row in rows:
            answers = [row.get(f"q{n}") for n in range(1, UAT_QUESTION_COUNT + 1)]
            if not all(isinstance(a, int) and not isinstance(a, bool) and 1 <= a <= 5 for a in answers):
                return JsonResponse({"ok": False, "error": "UAT answers must be 1-5."}, status=400)
            row["uat_score"] = round(sum(answers) / len(answers), 2)   # average rating, 1-5
            row["uat_version"] = UAT_VERSION
            row["uat_audience"] = uat_audience(request.user)  # which statement set they were shown

    # Who answered comes from the account, not from the form.
    name, role = request.user.get_full_name(), request.user.role_label
    for row in rows:
        if kind == SurveyResponse.SUS:
            row["respondent_name"], row["respondent_role"] = name, role
        else:
            row["tester_name"], row["tester_role"] = name, role
        if kind == SurveyResponse.UAT:
            # The day it was completed, in Philippine time (the server clock is UTC).
            row["test_date"] = timezone.localdate(timezone=PH_TIME).isoformat()

    SurveyResponse.objects.bulk_create(
        [SurveyResponse(survey_type=kind, user=request.user, data=row, is_dummy=request.user.answers_are_dummy) for row in rows]
    )
    return JsonResponse({"ok": True, "saved": len(rows)})
