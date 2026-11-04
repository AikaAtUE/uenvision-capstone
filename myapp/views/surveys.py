import json


from django.contrib.auth.decorators import login_required
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST

from ..models import (CustomUser, CurriculumSurveyResponse)
from .. import curriculum_data
from .. import ontology
from .common import _safe_json


# ---------------------------------------------------------------------------
# Curriculum-mapping surveys (Student / Fresh Grad Alumni / Professor)
#
# Students and alumni register first (student_views.register_view), then answer
# their survey logged in; faculty/administrators may open both to try them out. Each one is a single page: pick your program/year (or, for
# professors, just the subjects you teach), pick the subjects that apply,
# then tag the skills taught/learned per subject — curriculum_survey.js
# drives all of that dynamically from the JSON blobs below; the view's job
# is just to hand it the eligible subjects + ontology-suggested skills and
# to save the finished JSON payload.
#
# Which semester is "current" comes from curriculum_data.current_period(),
# worked out from today's date against the school calendar.
# ---------------------------------------------------------------------------
MAX_SUBJECTS_PER_SUBMISSION = 40


MAX_SKILLS_PER_SUBJECT = 30


MAX_JSON_BODY_BYTES = 200_000
UE_EMAIL_DOMAIN = "ue.edu.ph"  # students/alumni must use their UE email (subdomains allowed)


def _is_ue_email(value):
    try:
        validate_email(value)
    except ValidationError:
        return False
    domain = value.rsplit("@", 1)[1].lower()
    return domain == UE_EMAIL_DOMAIN or domain.endswith("." + UE_EMAIL_DOMAIN)


MAX_SECTION_LENGTH = 30


def _parse_curriculum_submission(request, needs_personal_info=True):
    """Shared POST-body parsing/sanity-checking for all three submit views.
    Returns (payload_dict, error_message_or_None)."""
    if len(request.body or b"") > MAX_JSON_BODY_BYTES:
        return None, "That submission is too large."
    try:
        payload = json.loads(request.body)
    except (ValueError, TypeError):
        return None, "Malformed request."
    if not isinstance(payload, dict):
        return None, "Malformed request."
    if payload.get("consent") is not True:
        return None, "Please confirm the Data Privacy notice before submitting."
    personal_info = payload.get("personal_info")
    if needs_personal_info and not isinstance(personal_info, dict):
        return None, "Missing personal information."
    subjects = payload.get("subjects")
    if not isinstance(subjects, list) or not 1 <= len(subjects) <= MAX_SUBJECTS_PER_SUBMISSION:
        return None, "Please select at least one subject."
    for subj in subjects:
        if not isinstance(subj, dict):
            return None, "Malformed subject entry."
        skills = subj.get("skills")
        if skills is not None and (not isinstance(skills, list) or len(skills) > MAX_SKILLS_PER_SUBJECT):
            return None, "Malformed skills entry."
    return payload, None


def _save_curriculum_survey(respondent_type, payload, user=None, dummy=False):
    return CurriculumSurveyResponse.objects.create(respondent_type=respondent_type, data=payload, user=user,
                                                   is_dummy=dummy or bool(user and user.answers_are_dummy))


def _is_dummy(request):
    """Answers sent while logged in as a dummy (test) account or a developer go to the dummy data set."""
    return request.user.is_authenticated and request.user.answers_are_dummy


def _learner_survey_saved(request, response):
    """After a student/alumni survey: it is linked to their account and they go to
    their dashboard. (Faculty / administrators trying the survey out just get a thank-you.)"""
    user = request.user
    if user.is_learner:
        response.user = user
        response.save(update_fields=["user"])
        return JsonResponse({"ok": True, "next_url": reverse("student_dashboard")})
    return JsonResponse({"ok": True})


def _learner_submit_check(request, kind):
    """Students and alumni register before answering (student_views.register_view).
    -> JsonResponse error, or None."""
    user = request.user
    if not user.is_authenticated:
        return JsonResponse({"ok": False, "error": "Please create your account or log in first.",
                             "register_url": reverse("register") + f"?as={kind}"}, status=401)
    if user.is_learner and user.role != kind:
        return JsonResponse({"ok": False, "error": "This survey is for the other group. Please open your own survey."}, status=403)
    return None


def _apply_account_info(request, payload, kind):
    """A registered student/alumni answers as their account: name and email come from it,
    and the rest of "About you" (which they may have corrected) is checked and saved back
    to the account. -> error message or None."""
    from ..student_views import clean_learner_info

    user = request.user
    if not user.is_learner:
        return None
    sent = payload["personal_info"]
    info, error = clean_learner_info(kind, sent)
    if error:
        return error
    payload["personal_info"] = {**sent, **info, "name": user.get_full_name(), "ue_email": user.email}
    if kind == "student":
        payload["personal_info"]["year_level"] = int(info["year_level"])
    if user.learner_info != info:
        user.learner_info = info
        user.save(update_fields=["learner_info"])
    return None


def _clean_target_role(payload):
    from .. import job_roles

    role = payload.get("target_role")
    payload["target_role"] = role if role in job_roles.ROLE_LABELS else ""


def _ue_email_error(payload):
    if not _is_ue_email(str(payload["personal_info"].get("ue_email") or "").strip()):
        return f"Please use your UE email address (ending in @{UE_EMAIL_DOMAIN})."
    return None


def _email_error(payload):
    try:
        validate_email(str(payload["personal_info"].get("ue_email") or "").strip())
    except ValidationError:
        return "Please enter a valid email address."
    return None


def _clean_learner_custom_subjects(payload):
    """Subjects a student / alumnus added because they aren't listed (their
    Professional Elective, ...): checked like a professor's, tagged with their course.
    Returns an error message or None."""
    program = str(payload["personal_info"].get("course") or "")
    for i, subj in enumerate(payload["subjects"]):
        if isinstance(subj, dict) and subj.get("custom"):
            info, error = curriculum_data.clean_learner_custom_subject(subj, program)
            if error:
                return error
            payload["subjects"][i] = {**subj, **info, "term": "added", "term_label": "Added by you"}
    return None


@require_POST
def student_survey_submit_view(request):
    refused = _learner_submit_check(request, "student")
    if refused:
        return refused
    payload, error = _parse_curriculum_submission(request)
    if error:
        return JsonResponse({"ok": False, "error": error}, status=400)
    error = _apply_account_info(request, payload, "student")
    if error:
        return JsonResponse({"ok": False, "error": error}, status=400)
    error = _clean_learner_custom_subjects(payload)
    if error:
        return JsonResponse({"ok": False, "error": error}, status=400)
    error = None if request.user.is_learner else _ue_email_error(payload)   # theirs is the account's
    if error:
        return JsonResponse({"ok": False, "error": error}, status=400)
    terms = {s.get("term") for s in payload["subjects"] if isinstance(s, dict)}
    if "current" not in terms:
        return JsonResponse({"ok": False, "error": "Please select at least one current-semester subject."}, status=400)
    if payload.get("has_previous") and "previous" not in terms:
        return JsonResponse({"ok": False, "error": "Please select at least one previous-semester subject."}, status=400)
    # Section is asked of students only (alumni no longer have one).
    section = str(payload["personal_info"].get("section") or "").strip()
    if not section:
        return JsonResponse({"ok": False, "error": "Please enter your section."}, status=400)
    if len(section) > MAX_SECTION_LENGTH:
        return JsonResponse({"ok": False, "error": "That section is too long."}, status=400)
    payload["personal_info"]["section"] = section
    _clean_target_role(payload)
    response = _save_curriculum_survey(CurriculumSurveyResponse.STUDENT, payload, dummy=_is_dummy(request))
    return _learner_survey_saved(request, response)


@require_POST
def alumni_survey_submit_view(request):
    refused = _learner_submit_check(request, "alumni")
    if refused:
        return refused
    payload, error = _parse_curriculum_submission(request)
    if error:
        return JsonResponse({"ok": False, "error": error}, status=400)
    error = _apply_account_info(request, payload, "alumni")
    if error:
        return JsonResponse({"ok": False, "error": error}, status=400)
    error = _clean_learner_custom_subjects(payload)
    if error:
        return JsonResponse({"ok": False, "error": error}, status=400)
    # theirs is the account's; alumni may use any email (they may have lost their UE one)
    error = None if request.user.is_learner else _email_error(payload)
    if error:
        return JsonResponse({"ok": False, "error": error}, status=400)
    employment = payload.get("employment")
    if not isinstance(employment, dict):
        return JsonResponse({"ok": False, "error": "Missing employment information."}, status=400)
    _clean_target_role(payload)
    response = _save_curriculum_survey(CurriculumSurveyResponse.ALUMNI, payload, dummy=_is_dummy(request))
    return _learner_survey_saved(request, response)


@login_required
@require_POST
def professor_survey_submit_view(request):
    """Saves the professor's record. The Professor Survey page is also where they
    edit it later, so a professor who already has a record gets it updated in
    place (one record per professor) instead of a second response."""
    from ..student_views import latest_response

    payload, error = _parse_curriculum_submission(request, needs_personal_info=False)
    if error:
        return JsonResponse({"ok": False, "error": error}, status=400)
    payload.pop("personal_info", None)  # the response is linked to the account instead
    current = latest_response(request.user)
    earlier = {s.get("code") for s in ((current.data or {}).get("subjects") or []) if isinstance(s, dict)} if current else set()
    by_code = curriculum_data.subject_by_code()
    subjects, seen = [], set()
    for subj in payload["subjects"]:
        if subj.get("custom"):
            info, error = curriculum_data.clean_custom_subject(subj)
            if error:
                return JsonResponse({"ok": False, "error": error}, status=400)
            subj = {**subj, **info}
        elif str(subj.get("code") or "") not in by_code or (
                subj["code"] in curriculum_data.HIDDEN_FROM_PROFESSORS and subj["code"] not in earlier):
            return JsonResponse({"ok": False, "error": "Unknown subject."}, status=400)
        if subj["code"] not in seen:
            seen.add(subj["code"])
            subjects.append(subj)
    payload["subjects"] = subjects
    now = timezone.now().isoformat(timespec="seconds")
    if current is None:
        payload["consent_at"] = now
        _save_curriculum_survey(CurriculumSurveyResponse.PROFESSOR, payload, user=request.user)
        # First answer: faculty were held on this page until now, so take them in.
        return JsonResponse({"ok": True, "created": True, "next_url": reverse("dashboard")})
    data = dict(current.data or {})
    data.update(payload)
    data.setdefault("consent_at", current.created_at.isoformat(timespec="seconds"))
    data["edited_at"] = now
    current.data = data
    current.save(update_fields=["data"])
    return JsonResponse({"ok": True, "created": False, "edited_at": now})


def _survey_draft_key(request, survey):
    """localStorage key under which curriculum-survey.js keeps unfinished answers
    (cleared once submitted). Only for logged-in users, so a draft is never shown
    to someone else using the same browser; None turns drafts off."""
    if not request.user.is_authenticated:
        return None
    return f"ue_survey_draft:{survey}:{request.user.pk}"


def _learner_survey_gate(request, kind):
    """Students / alumni register first: someone not logged in goes to registration,
    and a student opening the alumni survey (or the other way round) to their own.
    Faculty / administrators may still open both to try them out. -> redirect or None."""
    from ..student_views import survey_url_for

    user = request.user
    role = request.GET.get("role", "")
    if not user.is_authenticated:
        url = reverse("register") + f"?as={kind}"
        from .. import job_roles
        return redirect(url + (f"&role={role}" if role in job_roles.ROLE_LABELS else ""))
    if user.is_learner and user.role != kind:
        return redirect(survey_url_for(user.role, role))
    return None


def _prefill(user):
    """The survey's "About you", filled in from the student's / alumni's registration."""
    if not user.is_learner:
        return None
    info = dict(user.learner_info or {})
    year = str(info.get("year_level") or "")
    suffix = {"1": "st", "2": "nd", "3": "rd"}.get(year, "th")
    needed = ("student_number", "course") + (("year_graduated",) if user.role == user.Role.ALUMNI
                                             else ("year_level", "section"))
    return {**info, "name": user.get_full_name(), "email": user.email,
            "year_label": f"{year}{suffix} Year" if year else "",
            # accounts an administrator made have no details yet: then the fields show open
            "complete": all(info.get(k) for k in needed)}


def _target_role(request):
    """?role=... from the homepage, or the job role saved on their account."""
    role = request.GET.get("role", "")
    if not role and request.user.is_authenticated:
        role = request.user.target_role or ""
    return role


def student_survey_view(request):
    gate = _learner_survey_gate(request, "student")
    if gate:
        return gate
    period = curriculum_data.current_period()
    bootstrap = {
        "draftKey": _survey_draft_key(request, "student"),
        "programLabels": curriculum_data.PROGRAM_LABELS,
        "yearLevels": curriculum_data.YEAR_LEVELS,
        "currentSemLabel": period["current_label"],
        "ueEmailDomain": UE_EMAIL_DOMAIN,
        "eligibility": curriculum_data.build_student_eligibility(period["slot"]),
        "knownCodes": sorted(curriculum_data.subject_by_code()),
        "targetRole": _target_role(request),
        "skills": ontology.subject_skill_map(),
        "termTags": curriculum_data.subject_term_tags(),
        "submitUrl": reverse("student_survey_submit"),
        "skillSearchUrl": reverse("skill_search"),
        "skillAddUrl": reverse("skill_add"),
    }
    return render(request, "student_survey.html", {
        "prefill": _prefill(request.user),
        "is_placeholder_curriculum": curriculum_data.CURRICULUM_IS_PLACEHOLDER,
        "bootstrap_json": _safe_json(bootstrap),
    })


def alumni_survey_view(request):
    gate = _learner_survey_gate(request, "alumni")
    if gate:
        return gate
    from ..student_views import max_grad_year
    terms_by_program = {
        program: curriculum_data.term_sequence(program)
        for program in curriculum_data.PROGRAMS
    }
    bootstrap = {
        "draftKey": _survey_draft_key(request, "alumni"),
        "programLabels": curriculum_data.PROGRAM_LABELS,
        "termsByProgram": terms_by_program,
        "subjectsByProgramTerm": curriculum_data.learner_subjects_by_term(),
        "knownCodes": sorted(curriculum_data.subject_by_code()),
        "targetRole": _target_role(request),
        "ueEmailDomain": UE_EMAIL_DOMAIN,
        "skills": ontology.subject_skill_map(),
        "termTags": curriculum_data.subject_term_tags(),
        "submitUrl": reverse("alumni_survey_submit"),
        "skillSearchUrl": reverse("skill_search"),
        "skillAddUrl": reverse("skill_add"),
    }
    return render(request, "alumni_survey.html", {
        "prefill": _prefill(request.user),
        "max_grad_year": max_grad_year(),
        "is_placeholder_curriculum": curriculum_data.CURRICULUM_IS_PLACEHOLDER,
        "bootstrap_json": _safe_json(bootstrap),
    })


@login_required
def professor_survey_view(request):
    """The Professor Survey, which is also the professor's editable record: once
    answered, the page opens with their saved subjects and skills filled in."""
    from ..student_views import latest_response

    period = curriculum_data.current_period()
    current = latest_response(request.user)
    data = (current.data or {}) if current else {}
    by_code = curriculum_data.subject_by_code()
    record = None
    if current:
        record = [{"code": subj["code"],
                   "name": subj.get("name") or by_code.get(subj["code"], {}).get("name", ""),
                   "custom": bool(subj.get("custom")), "programs": subj.get("programs") or [],
                   "skills": [s for s in (subj.get("skills") or []) if isinstance(s, dict)]}
                  for subj in data.get("subjects") or [] if isinstance(subj, dict) and subj.get("code")]
    consent_at = data.get("consent_at") or (current.created_at.isoformat() if current and data.get("consent") else None)
    bootstrap = {
        # drafts only for a first answer: editing a saved record keeps its "Unsaved changes" warning
        "draftKey": _survey_draft_key(request, "professor") if current is None else None,
        "currentSemLabel": period["current_label"],
        "previousSemLabel": period["previous_sem_label"],
        "previousSummerLabel": period["previous_summer_label"],
        "pools": curriculum_data.professor_term_pools(period["slot"]),
        "knownCodes": sorted(by_code),
        "record": record,
        "consented": bool(consent_at),
        "skills": ontology.subject_skill_map(),
        "termTags": curriculum_data.subject_term_tags(),
        "submitUrl": reverse("professor_survey_submit"),
        "skillSearchUrl": reverse("skill_search"),
        "skillAddUrl": reverse("skill_add"),
    }
    return render(request, "professor_survey.html", {
        "active_page": "data",
        "data_tab": "professor_survey",
        "has_record": current is not None,
        "required_first": current is None and request.user.role == CustomUser.Role.FACULTY,
        "consent_at": parse_datetime(consent_at) if consent_at else None,
        "edited_at": parse_datetime(data["edited_at"]) if data.get("edited_at") else (current.created_at if current else None),
        "is_placeholder_curriculum": curriculum_data.CURRICULUM_IS_PLACEHOLDER,
        "current_sem_label": period["current_label"],
        "previous_sem_label": period["previous_sem_label"],
        "previous_summer_label": period["previous_summer_label"],
        "bootstrap_json": _safe_json(bootstrap),
    })
