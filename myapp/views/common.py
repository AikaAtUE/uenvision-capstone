import json

from functools import wraps
from datetime import timedelta, timezone as dt_timezone

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils.safestring import mark_safe


def home_url_for(user):
    """Where a logged-in user lands: students/alumni get their own dashboard, and anyone
    with a temporary password goes to Settings to choose their own."""
    if getattr(user, "must_change_password", False):
        return reverse("settings")
    return reverse("student_dashboard") if getattr(user, "is_learner", False) else reverse("dashboard")


# ---------------------------------------------------------------------------
# Accounts management (Administrator only)
# ---------------------------------------------------------------------------
def administrator_required(view):
    """Logged-in Administrators only. Everyone else gets a 403, even if they type the URL."""
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_administrator:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper


PH_TIME = dt_timezone(timedelta(hours=8), "PHT")  # no DST; avoids needing tzdata on Windows


def _sees_dummy_results(request):
    """Dummy accounts always see results computed from dummy answers. Developers see the
    real results unless they've flipped the Real / Dummy switch to Dummy."""
    from ..context_processors import DEV_DUMMY_VIEW_KEY
    user = request.user
    return user.is_dummy or (user.is_developer and bool(request.session.get(DEV_DUMMY_VIEW_KEY)))


def _sees_student_view(request):
    """Developers test both sides: with the Faculty / Student view switch on Student, the
    Dashboard and Recommendations show the student / alumni skill gap page instead."""
    from ..context_processors import DEV_STUDENT_VIEW_KEY
    return request.user.is_developer and bool(request.session.get(DEV_STUDENT_VIEW_KEY))


def _safe_json(obj):
    """mark_safe()'d JSON for embedding in a <script type="application/json">
    tag — escapes "</" so nothing in the data can break out of the tag."""
    return mark_safe(json.dumps(obj).replace("</", "<\\/"))
