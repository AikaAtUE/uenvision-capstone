import json

from functools import wraps

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404, HttpResponse
from django.views.decorators.http import require_POST

from .models import CustomUser, SurveyResponse, MIN_PASSWORD_LENGTH, DEFAULT_PASSWORD

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

        if len(password or "") < MIN_PASSWORD_LENGTH:
            return render(request, "signup.html", {"error": f"Password must be at least {MIN_PASSWORD_LENGTH} characters."})

        if CustomUser.objects.filter(email=email).exists():
            return render(request, "signup.html", {"error": "An account with this email already exists."})

        user = CustomUser.objects.create_user(
            email=email,
            password=password,
            first_name=first_name,
            middle_name=middle_name,
            last_name=last_name,
            role=CustomUser.Role.FACULTY,  # self-signups are always Faculty; only an admin can create admins
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
    return render(request, "settings.html", {"active_page": "settings", "min_password_length": MIN_PASSWORD_LENGTH})


@login_required
@require_POST
def change_password_view(request):
    current = request.POST.get("current_password", "")
    new = request.POST.get("new_password", "")
    confirm = request.POST.get("confirm_password", "")

    if not request.user.check_password(current):
        messages.error(request, "Current password is incorrect.")
    elif len(new) < MIN_PASSWORD_LENGTH:
        messages.error(request, f"New password must be at least {MIN_PASSWORD_LENGTH} characters.")
    elif new != confirm:
        messages.error(request, "New password and confirmation do not match.")
    elif new == current:
        messages.error(request, "New password must be different from your current password.")
    else:
        request.user.set_password(new)
        request.user.save(update_fields=["password"])
        update_session_auth_hash(request, request.user)  # keep this session logged in
        messages.success(request, "Your password has been changed.")
    return redirect("settings")


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


def _clean_account_fields(post, exclude_pk=None):
    """Validate the name/email fields shared by create + edit. Returns (data, error)."""
    data = {
        "last_name": post.get("last_name", "").strip(),
        "first_name": post.get("first_name", "").strip(),
        "middle_name": post.get("middle_name", "").strip(),
        "email": post.get("email", "").strip(),
    }
    if not data["last_name"] or not data["first_name"]:
        return data, "First name and last name are required."
    try:
        validate_email(data["email"])
    except ValidationError:
        return data, "Enter a valid email address."
    data["email"] = CustomUser.objects.normalize_email(data["email"])
    clash = CustomUser.objects.filter(email__iexact=data["email"])
    if exclude_pk is not None:
        clash = clash.exclude(pk=exclude_pk)
    if clash.exists():
        return data, "An account with this email already exists."
    return data, None


@administrator_required
def accounts_view(request):
    accounts = CustomUser.objects.order_by("last_name", "first_name")
    return render(request, "accounts.html", {
        "active_page": "accounts",
        "accounts": accounts,
        "roles": CustomUser.Role.choices,
        "min_password_length": MIN_PASSWORD_LENGTH,
        "default_password": DEFAULT_PASSWORD,
    })


@administrator_required
@require_POST
def account_create_view(request):
    data, error = _clean_account_fields(request.POST)
    role = request.POST.get("role", CustomUser.Role.FACULTY)
    password = request.POST.get("password", "") or DEFAULT_PASSWORD  # blank -> default

    if not error and role not in CustomUser.Role.values:
        error = "Choose a valid role."
    if not error and len(password) < MIN_PASSWORD_LENGTH:
        error = f"Password must be at least {MIN_PASSWORD_LENGTH} characters."

    if error:
        messages.error(request, error)
    else:
        CustomUser.objects.create_user(password=password, role=role, **data)
        note = " with the default password." if password == DEFAULT_PASSWORD else "."
        messages.success(request, f"Account created for {data['email']}{note}")
    return redirect("accounts")


@administrator_required
@require_POST
def account_edit_view(request, pk):
    target = get_object_or_404(CustomUser, pk=pk)
    data, error = _clean_account_fields(request.POST, exclude_pk=target.pk)
    if error:
        messages.error(request, error)
    else:
        for field, value in data.items():
            setattr(target, field, value)
        target.save(update_fields=list(data))
        messages.success(request, f"Account updated for {target.email}.")
    return redirect("accounts")


@administrator_required
@require_POST
def account_reset_password_view(request, pk):
    target = get_object_or_404(CustomUser, pk=pk)
    target.set_password(DEFAULT_PASSWORD)
    target.save(update_fields=["password"])
    if target.pk == request.user.pk:
        update_session_auth_hash(request, target)  # `target` holds the new hash; request.user is stale
    messages.success(request, f"Password for {target.email} was reset to the default ({DEFAULT_PASSWORD}).")
    return redirect("accounts")


@administrator_required
@require_POST
def account_delete_view(request, pk):
    target = get_object_or_404(CustomUser, pk=pk)
    if target.pk == request.user.pk:
        messages.error(request, "You can't remove your own account from here.")
    else:
        email = target.email
        target.delete()
        messages.success(request, f"Account {email} was removed.")
    return redirect("accounts")


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