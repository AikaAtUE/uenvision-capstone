import time
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import logout
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import Resolver404, resolve, reverse

# Pages a logged-in student/alumni may open. Everything else in the app (the
# faculty/administrator Dashboard, Data, Recommendations, Accounts, Console, ...)
# sends them back to their own dashboard.
LEARNER_URL_NAMES = {
    "home", "role_skills", "check_gap", "skill_search", "skill_add", "register", "login", "logout",
    "student_dashboard", "student_role", "student_generate", "my_skills", "my_skills_save",
    "student_survey", "student_survey_submit", "alumni_survey", "alumni_survey_submit",
    "feedback", "survey_submit", "feedback_later", "about", "help", "settings", "change_password", "session_ping",
    "verify_email", "resend_verification", "forgot_password", "reset_password", "reset_password_confirm",
}

# Dummy (test) students can also open the overall Dashboard, which for them is
# computed from dummy answers only.
DUMMY_LEARNER_URL_NAMES = {"dashboard", "dashboard_skills"}


class LearnerAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and getattr(user, "is_learner", False):
            try:
                match = resolve(request.path_info)
            except Resolver404:
                match = None
            allowed = LEARNER_URL_NAMES | (DUMMY_LEARNER_URL_NAMES if user.is_dummy else set())
            if match is not None and match.url_name not in allowed:
                return redirect("student_dashboard")
        return self.get_response(request)


# Session key holding the time (epoch seconds) of the user's last real request.
LAST_ACTIVITY_KEY = "last_activity"
# Background requests (e.g. the Data > Scrape status poll) send this header so an
# open tab doesn't keep an idle user signed in forever.
BACKGROUND_HEADER = "HTTP_X_BACKGROUND_REQUEST"


def _wants_json(request):
    return (request.headers.get("x-requested-with") == "XMLHttpRequest"
            or "application/json" in request.headers.get("accept", "")
            or request.content_type == "application/json"
            or BACKGROUND_HEADER in request.META)


class IdleTimeoutMiddleware:
    """Log out any signed-in user (all roles) after IDLE_TIMEOUT_SECONDS without activity."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        timeout = getattr(settings, "IDLE_TIMEOUT_SECONDS", 1800)
        request.idle_timeout_seconds = timeout  # read by idle-timeout.js via base.html
        if timeout and user is not None and user.is_authenticated:
            now = int(time.time())
            last = request.session.get(LAST_ACTIVITY_KEY)
            if last is not None and now - last > timeout:
                logout(request)
                if _wants_json(request):
                    return JsonResponse({"ok": False, "error": "You were logged out after 30 minutes of inactivity. Please log in again.",
                                         "session_expired": True}, status=401)
                login_url = reverse("login")
                params = {"timeout": "1"}
                if request.method == "GET":
                    params["next"] = request.get_full_path()
                return redirect(f"{login_url}?{urlencode(params)}")
            # Only write the session when the stamp is missing or a little stale,
            # so normal browsing doesn't save the session on every request.
            if BACKGROUND_HEADER not in request.META and (last is None or now - last >= min(15, timeout // 10)):
                request.session[LAST_ACTIVITY_KEY] = now
        return self.get_response(request)


# What a faculty member who signed up themselves can open until an administrator approves them.
PENDING_URL_NAMES = {
    "pending_approval", "logout", "login", "session_ping", "verify_email", "resend_verification",
    "forgot_password", "reset_password", "reset_password_confirm", "home", "about",
}


class PendingApprovalMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not getattr(user, "is_approved", True):
            try:
                match = resolve(request.path_info)
            except Resolver404:
                match = None
            if match is not None and match.url_name not in PENDING_URL_NAMES:
                if _wants_json(request):
                    return JsonResponse({"ok": False, "error": "Your account is waiting for approval."}, status=403)
                return redirect("pending_approval")
        return self.get_response(request)


# What a user with a temporary password (set by an administrator) can open until they choose their own.
PASSWORD_CHANGE_URL_NAMES = {
    "settings", "change_password", "logout", "login", "session_ping", "verify_email", "resend_verification",
    "forgot_password", "reset_password", "reset_password_confirm",
}


class ForcePasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and getattr(user, "must_change_password", False):
            try:
                match = resolve(request.path_info)
            except Resolver404:
                match = None
            if match is not None and match.url_name not in PASSWORD_CHANGE_URL_NAMES:
                if _wants_json(request):
                    return JsonResponse({"ok": False, "error": "Please choose a new password first."}, status=403)
                return redirect("settings")
        return self.get_response(request)


# What a faculty member with no Professor Survey answer yet can open: the survey itself
# (and the skill search it uses), plus account basics. Everything else sends them to the
# survey first, the same way students and alumni answer theirs before getting an account.
PROFESSOR_SURVEY_URL_NAMES = {
    "professor_survey", "professor_survey_submit", "skill_search", "skill_add",
    "settings", "change_password", "logout", "login", "session_ping", "help", "about",
    "verify_email", "resend_verification", "forgot_password", "reset_password", "reset_password_confirm",
}


def needs_professor_survey(user):
    """Faculty (not administrators or developers) who haven't answered the Professor Survey."""
    from .models import CurriculumSurveyResponse

    return (getattr(settings, "REQUIRE_PROFESSOR_SURVEY", True)
            and user.role == user.Role.FACULTY
            and not CurriculumSurveyResponse.objects.filter(
                user=user, respondent_type=CurriculumSurveyResponse.PROFESSOR).exists())


class ProfessorSurveyFirstMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and getattr(user, "role", "") == "faculty":
            try:
                match = resolve(request.path_info)
            except Resolver404:
                match = None
            if match is not None and match.url_name not in PROFESSOR_SURVEY_URL_NAMES and needs_professor_survey(user):
                if _wants_json(request):
                    return JsonResponse({"ok": False, "error": "Please answer the Professor Survey first."}, status=403)
                return redirect(f"{reverse('professor_survey')}?first=1")
        return self.get_response(request)
