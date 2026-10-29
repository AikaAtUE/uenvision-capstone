"""Data > Survey Tracker (developers only): which accounts still haven't answered their
curriculum survey (Student / Alumni / Professor) or the Feedback surveys (SUS, and for
everyone but students and alumni, the UAT and test case sheet), with a reminder email.

Reminders are limited to one per account per day; the time of the last one is kept in
the cache (settings.CACHES), which is enough to show "reminded today" and stop repeats."""
import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import CurriculumSurveyResponse, CustomUser, SurveyResponse
from .views import _data_ctx

log = logging.getLogger(__name__)

REMIND_EVERY_SECONDS = 24 * 3600
ROLE_FILTERS = [("", "All roles"), ("learners", "Students and alumni"), ("faculty", "Faculty"),
                ("staff", "Administrators and developers")]
SHOW_FILTERS = [("missing", "Missing something"), ("all", "Everyone")]


def developer_required(view):
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_developer:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    wrapper.__name__ = view.__name__
    return wrapper


def _reminded_key(pk):
    return f"survey-reminder:{pk}"


def tracker_rows(users):
    """One row per account: its role and, per survey, True (answered) / False (missing) /
    None (not asked of this role)."""
    curriculum = {}
    for user_id, rtype in CurriculumSurveyResponse.objects.filter(user__in=users).values_list("user_id", "respondent_type"):
        curriculum.setdefault(user_id, set()).add(rtype)
    feedback = {}
    for user_id, stype in SurveyResponse.objects.filter(user__in=users).values_list("user_id", "survey_type").distinct():
        feedback.setdefault(user_id, set()).add(stype)
    rows = []
    for u in users:
        mine = curriculum.get(u.pk, set())
        if u.is_learner:
            curr = bool(mine & {CurriculumSurveyResponse.STUDENT, CurriculumSurveyResponse.ALUMNI})
        else:
            curr = CurriculumSurveyResponse.PROFESSOR in mine
        done = feedback.get(u.pk, set())
        cells = {
            "curriculum": curr,
            "sus": SurveyResponse.SUS in done,
            "uat": None if u.is_learner else SurveyResponse.UAT in done,
            "functional": None if u.is_learner else SurveyResponse.FUNCTIONAL in done,
        }
        reminded = cache.get(_reminded_key(u.pk))
        rows.append({
            "user": u,
            "cells": cells,
            "missing": [k for k, v in cells.items() if v is False],
            "reminded_at": parse_datetime(reminded) if reminded else None,
        })
    return rows


MISSING_LABELS = {"curriculum": "your curriculum survey", "sus": "the SUS evaluation",
                  "uat": "the UAT survey", "functional": "the functional test case sheet"}


@developer_required
def survey_tracker_view(request):
    role = request.GET.get("role", "")
    show = request.GET.get("show", "missing")
    users = CustomUser.objects.filter(is_active=True).order_by("role", "last_name", "first_name")
    if role == "learners":
        users = users.filter(role__in=[CustomUser.Role.STUDENT, CustomUser.Role.ALUMNI])
    elif role == "faculty":
        users = users.filter(role=CustomUser.Role.FACULTY)
    elif role == "staff":
        users = users.filter(role__in=[CustomUser.Role.ADMINISTRATOR, CustomUser.Role.DEVELOPER])
    else:
        role = ""
    rows = tracker_rows(list(users))
    totals = {k: sum(1 for r in rows if r["cells"][k]) for k in MISSING_LABELS}
    asked = {k: sum(1 for r in rows if r["cells"][k] is not None) for k in MISSING_LABELS}
    if show != "all":
        show = "missing"
        rows = [r for r in rows if r["missing"]]
    return render(request, "data_survey_tracker.html", _data_ctx(
        request, "tracker", rows=rows, role=role, show=show, role_filters=ROLE_FILTERS,
        show_filters=SHOW_FILTERS, totals=totals, asked=asked, email_configured=bool(settings.EMAIL_HOST),
    ))


def send_reminder(request, user, missing):
    # Log in straight into the first thing they still have to answer.
    target = reverse("professor_survey") if missing[0] == "curriculum" else f"{reverse('feedback')}?survey={missing[0]}"
    ctx = {"user": user, "items": [MISSING_LABELS[k] for k in missing],
           "url": request.build_absolute_uri(f"{reverse('login')}?{urlencode({'next': target})}")}
    try:
        send_mail(
            subject="A quick favor: your UEnvision surveys",
            message=render_to_string("emails/survey_reminder.txt", ctx),
            html_message=render_to_string("emails/survey_reminder.html", ctx),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
        )
    except Exception:
        log.exception("Could not send the survey reminder to %s", user.email)
        return False
    cache.set(_reminded_key(user.pk), timezone.now().isoformat(), REMIND_EVERY_SECONDS)
    return True


@developer_required
@require_POST
def survey_tracker_remind_view(request):
    next_url = request.POST.get("next") or ""
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse("survey_tracker")
    ids = [int(i) for i in request.POST.getlist("ids") if i.isdigit()]
    if not ids:
        messages.error(request, "Choose at least one account to remind.")
        return redirect(next_url)
    sent = skipped = failed = 0
    for row in tracker_rows(list(CustomUser.objects.filter(pk__in=ids, is_active=True))):
        if not row["missing"] or row["reminded_at"]:
            skipped += 1
        elif send_reminder(request, row["user"], row["missing"]):
            sent += 1
        else:
            failed += 1
    parts = [f"Sent {sent} reminder{'' if sent == 1 else 's'}."]
    if skipped:
        parts.append(f"Skipped {skipped} (already reminded today, or nothing missing).")
    if failed:
        parts.append(f"{failed} couldn't be sent; check the email settings.")
    (messages.warning if failed else messages.success)(request, " ".join(parts))
    return redirect(next_url)
