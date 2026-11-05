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
