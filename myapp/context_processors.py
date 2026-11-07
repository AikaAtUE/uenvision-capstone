from . import notifications

# Session key for a developer's Real / Dummy results switch (see views.developer_results_view).
DEV_DUMMY_VIEW_KEY = "dev_dummy_view"
# Session key for a developer's Faculty / Student / Alumni view switch: "student" or "alumni" =
# Dashboard and Recommendations show what that learner sees (their skill gap page) instead of
# the faculty pages; empty = Faculty view. (Older sessions may still hold True = "student".)
DEV_STUDENT_VIEW_KEY = "dev_student_view"


def dev_learner_view(request):
    """"student", "alumni" or None (Faculty view) for a developer's view switch."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not user.is_developer:
        return None
    value = request.session.get(DEV_STUDENT_VIEW_KEY)
    if value is True:
        return "student"
    return value if value in ("student", "alumni") else None


def admin_notifications(request):
    """Unread count and latest items for the notification bell (administrators only)."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not user.is_administrator:
        return {}
    from .models import Notification

    recent = list(Notification.objects.filter(recipient=user).select_related("subject_user")[:8])
    context = {"unread_notifications": notifications.unread_count(user), "recent_notifications": recent}
    if user.is_developer:
        # which results the Real / Dummy switch on the dashboard and recommendations is set to
        context["dev_dummy_view"] = bool(request.session.get(DEV_DUMMY_VIEW_KEY))
        # and which perspective the Faculty / Student view switch is set to
        context["dev_learner_view"] = dev_learner_view(request)
        context["dev_student_view"] = bool(context["dev_learner_view"])
    return context


# Time zone the "Data last updated" line is shown in (the server itself runs in UTC).
DISPLAY_TIME_ZONE = "Asia/Manila"


def skills_data_updated(request):
    """{"skills_data_updated": "Nov 4, 2026, 3:12 PM"} for the line under every top skills chart
    (_data_updated.html): when the extracted skills data was last written by Extract Skills or
    Import Data. Empty when there is no data yet."""
    from zoneinfo import ZoneInfo

    from .pipeline import manager as pipeline

    try:
        when = pipeline.skills_data_updated()
    except OSError:
        when = None
    if when is None:
        return {}
    local = when.astimezone(ZoneInfo(DISPLAY_TIME_ZONE))
    hour = local.strftime("%I").lstrip("0") or "12"
    return {"skills_data_updated": f"{local:%b} {local.day}, {local.year}, {hour}:{local:%M} {local:%p}"}


def onboarding_tour(request):
    """{"tour_config": {...}} for onboarding-tour.js (base.html): which tours this account has
    already seen, and the URLs the tour needs (saving "seen", and the pages the administrator
    tour moves to). Logged-in users only."""
    from django.urls import reverse

    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    seen = [t for t in (user.tours_seen or []) if t in user.TOURS]
    return {"tour_config": {
        "seen": seen,
        "learner": user.is_learner,
        "admin": user.is_administrator,
        "saveUrl": reverse("tour_seen"),
        # admin page links only for administrators, so other users' pages never name them
        "urls": {
            "extraction": reverse("data_extraction"),
            "accounts": reverse("accounts"),
        } if user.is_administrator else {},
    }}
