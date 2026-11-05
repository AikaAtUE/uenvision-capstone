import json


from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from ..models import SurveyResponse
from .. import feedback_forms, feedback_nudge
from .common import PH_TIME


@login_required
def feedback_view(request):
    audience = sus_audience(request.user)
    content = feedback_forms.get_all()   # purposes, instructions and questions (developers can edit them)
    return render(request, "feedback.html", {"active_page": "feedback",
                                             "sus_first_statement": content["sus"]["first_statements"][audience],
                                             "uat_audience": uat_audience(request.user),
                                             "forms": content,
                                             "can_edit_forms": request.user.is_developer,
                                             "saved_feedback": saved_feedback(request.user)})


@login_required
@require_POST
def feedback_form_save_view(request, key):
    """Developers only: save their edit of one Feedback survey's contents ("Edit form"), or
    {"reset": true} to go back to the original contents. The new contents show for everyone."""
    from ..models import FeedbackForm

    if not request.user.is_developer:
        return JsonResponse({"ok": False, "error": "Only developers can edit the feedback forms."}, status=403)
    if key not in feedback_forms.KEYS:
        return JsonResponse({"ok": False, "error": "Unknown form."}, status=404)
    if len(request.body or b"") > 200_000:
        return JsonResponse({"ok": False, "error": "That is too large."}, status=400)
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"ok": False, "error": "Malformed request."}, status=400)
    if not isinstance(body, dict):
        return JsonResponse({"ok": False, "error": "Malformed request."}, status=400)
    if body.get("reset"):
        FeedbackForm.objects.filter(key=key).delete()
    else:
        try:
            content = feedback_forms.clean(key, body.get("content"))
        except ValueError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
        FeedbackForm.objects.update_or_create(key=key, defaults={"content": content, "updated_by": request.user})
    return JsonResponse({"ok": True, "content": feedback_forms.get_all()[key]})


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
# (the default wording; developers can change it on the Feedback page, see feedback_forms.py)
SUS_FIRST_STATEMENTS = dict(feedback_forms.DEFAULTS["sus"]["first_statements"])


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


# ---------------------------------------------------------------------------
# Editing a submitted feedback survey
# Each account keeps ONE answer per survey (and per version for SUS / UAT): submitting
# again replaces it instead of adding another row, so the Feedback page can show the
# saved answers with an "Edit answers" button. Accounts that already have several rows
# from before this change keep them all (nothing is deleted); the latest one is the one
# shown and the one an edit replaces.
# ---------------------------------------------------------------------------
def _version_filter(kind):
    """The data__ lookup that limits a user's rows to the survey version answered now."""
    if kind == SurveyResponse.SUS:
        return {"data__sus_version": SUS_VERSION}
    if kind == SurveyResponse.UAT:
        return {"data__uat_version": UAT_VERSION}
    return {}


def _latest(user, kind, lock=False):
    qs = SurveyResponse.objects.filter(user=user, survey_type=kind, **_version_filter(kind))
    if lock:
        qs = qs.select_for_update()
    return qs.order_by("-created_at", "-pk").first()


def _latest_functional_rows(user, lock=False):
    """The rows of this account's latest functional test sheet (one submission_id), oldest first."""
    last = _latest(user, SurveyResponse.FUNCTIONAL, lock=lock)
    if last is None:
        return []
    sid = (last.data or {}).get("submission_id")
    if not sid:
        return [last]
    qs = SurveyResponse.objects.filter(user=user, survey_type=SurveyResponse.FUNCTIONAL, data__submission_id=sid)
    if lock:
        qs = qs.select_for_update()
    return list(qs.order_by("pk"))


def _when(resp):
    data = resp.data or {}
    return {"submitted_at": timezone.localtime(resp.created_at, PH_TIME).strftime("%b %d, %Y").replace(" 0", " "),
            "edited_at": data.get("edited_at") or ""}


def saved_feedback(user):
    """What this account already answered on the Feedback page, for survey.js to fill in:
    {"sus": {...answers, submitted_at}, "uat": {...}, "functional": {"rows": [...], submitted_at}}."""
    out = {}
    for kind in (SurveyResponse.SUS, SurveyResponse.UAT):
        resp = _latest(user, kind)
        if resp is not None:
            out[kind] = dict(resp.data or {}, **_when(resp))
    if not user.is_learner:
        rows = _latest_functional_rows(user)
        if rows:
            out[SurveyResponse.FUNCTIONAL] = dict(rows=[r.data for r in rows], **_when(rows[0]))
    return out


def _save_replacing(user, kind, rows):
    """Save `rows` as this account's answer to `kind`, replacing its latest earlier answer
    (same survey and version). Returns True if an earlier answer was replaced."""
    dummy = user.answers_are_dummy
    with transaction.atomic():
        if kind in (SurveyResponse.SUS, SurveyResponse.UAT):
            row = rows[0]
            existing = _latest(user, kind, lock=True)
            if existing is None:
                SurveyResponse.objects.create(survey_type=kind, user=user, data=row, is_dummy=dummy)
                return False
            row["edited_at"] = timezone.localtime(timezone.now(), PH_TIME).strftime("%b %d, %Y").replace(" 0", " ")
            existing.data, existing.is_dummy = row, dummy
            existing.save(update_fields=["data", "is_dummy"])
            return True
        # Functional sheet: one row per test case, all sharing a submission_id. An edit swaps
        # the rows of the latest sheet for the new ones and keeps its submission_id.
        old = _latest_functional_rows(user, lock=True)
        if old and (old[0].data or {}).get("submission_id"):
            sid = old[0].data["submission_id"]
            edited = timezone.localtime(timezone.now(), PH_TIME).strftime("%b %d, %Y").replace(" 0", " ")
            for row in rows:
                row["submission_id"], row["edited_at"] = sid, edited
            SurveyResponse.objects.filter(pk__in=[r.pk for r in old]).delete()
            replaced = True
        else:
            replaced = False
        SurveyResponse.objects.bulk_create(
            [SurveyResponse(survey_type=kind, user=user, data=row, is_dummy=dummy) for row in rows])
        return replaced


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
    if kind in (SurveyResponse.SUS, SurveyResponse.UAT) and len(rows) != 1:
        return JsonResponse({"ok": False, "error": "Send one answer at a time."}, status=400)
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

    replaced = _save_replacing(request.user, kind, rows)
    return JsonResponse({"ok": True, "saved": len(rows), "edited": replaced, "answers": saved_feedback(request.user).get(kind)})
