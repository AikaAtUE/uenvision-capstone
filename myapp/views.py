import json

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, HttpResponse
from django.views.decorators.http import require_POST

from .models import CustomUser, SurveyResponse

# Create your views here.

def login_view(request):
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")
        user = authenticate(request, username=email, password=password)
        if user is not None:
            login(request, user)
            return redirect("dashboard")
        return render(request, "login.html", {"error": "Invalid email or password."})
    return render(request, "login.html")


def signup_view(request):
    if request.method == "POST":
        last_name = request.POST.get("last_name")
        first_name = request.POST.get("first_name")
        middle_name = request.POST.get("middle_name", "")
        email = request.POST.get("email")
        password = request.POST.get("password")
        password2 = request.POST.get("password2")

        if password != password2:
            return render(request, "signup.html", {"error": "Passwords do not match."})

        if CustomUser.objects.filter(email=email).exists():
            return render(request, "signup.html", {"error": "An account with this email already exists."})

        user = CustomUser.objects.create_user(
            email=email,
            password=password,
            first_name=first_name,
            middle_name=middle_name,
            last_name=last_name,
        )
        login(request, user)
        return redirect("dashboard")
    return render(request, "signup.html")


def logout_view(request):
    logout(request)
    return redirect("login")


def forgot_password_view(request):
    return render(request, "forgot_password.html")


def reset_password_view(request):
    return render(request, "reset_password.html")


@login_required
def dashboard_view(request):
    return render(request, "dashboard.html", {"active_page": "dashboard"})


@login_required
def data_view(request):
    return render(request, "data.html", {"active_page": "data"})


@login_required
def feedback_view(request):
    return render(request, "feedback.html", {"active_page": "feedback"})


@login_required
def about_view(request):
    return render(request, "about.html", {"active_page": "about"})


@login_required
def settings_view(request):
    return render(request, "settings.html", {"active_page": "settings"})


# ---------------------------------------------------------------------------
# Feedback surveys (SUS / UAT / functional test sheet) — called by survey.js
# ---------------------------------------------------------------------------
MAX_SURVEY_ROWS = 200


def _compute_sus_score(answers):
    """Odd items score (answer - 1), even items score (5 - answer); sum x 2.5 = 0-100."""
    total = sum((a - 1) if i % 2 == 0 else (5 - a) for i, a in enumerate(answers))
    return round(total * 2.5, 2)


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

    if kind == SurveyResponse.SUS:
        for row in rows:
            answers = [row.get(f"q{n}") for n in range(1, 11)]
            if not all(isinstance(a, int) and not isinstance(a, bool) and 1 <= a <= 5 for a in answers):
                return JsonResponse({"ok": False, "error": "SUS answers must be 1-5."}, status=400)
            row["sus_score"] = _compute_sus_score(answers)  # never trust the client's score

    SurveyResponse.objects.bulk_create(
        [SurveyResponse(survey_type=kind, user=request.user, data=row) for row in rows]
    )
    return JsonResponse({"ok": True, "saved": len(rows)})