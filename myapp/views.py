import json
from urllib.parse import urlencode

from functools import wraps

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404, HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_GET, require_POST

from .models import (CustomUser, Notification, SurveyResponse, CurriculumSurveyResponse, MIN_PASSWORD_LENGTH,
                     make_temporary_password)
from .pipeline import manager as pipeline
from . import curriculum_data
from . import email_verification, feedback_nudge, notifications
from . import gap_analysis
from . import login_limits
from . import ontology
from . import recommendations

# Create your views here.

def home_url_for(user):
    """Where a logged-in user lands: students/alumni get their own dashboard, and anyone
    with a temporary password goes to Settings to choose their own."""
    if getattr(user, "must_change_password", False):
        return reverse("settings")
    return reverse("student_dashboard") if getattr(user, "is_learner", False) else reverse("dashboard")


def login_view(request):
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")
        wait = login_limits.blocked_for(request, email)
        if wait:
            return render(request, "login.html", {"error": login_limits.message(wait)}, status=429)
        user = authenticate(request, username=email, password=password)
        if user is None:
            login_limits.record_failure(request, email)
        else:
            login_limits.clear_email(email)
        # No email confirmation needed to log in: students/alumni who haven't confirmed
        # yet are reminded on their dashboard and in Settings instead.
        if user is not None:
            login(request, user)
            next_url = request.POST.get("next") or request.GET.get("next")
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)
            return redirect(home_url_for(user))
        return render(request, "login.html", {"error": "Invalid email or password."})
    if request.user.is_authenticated:
        return redirect(home_url_for(request.user))
    return render(request, "login.html", {"timed_out": request.GET.get("timeout") == "1"})


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
            email_verified=True,  # faculty can use UEnvision right away, without confirming their email
            # They can use everything right away too. An administrator still approves them on the
            # Accounts page, or removes them (with their answers) if they aren't faculty.
            is_approved=False,
        )
        notifications.notify_faculty_signup(request, user)
        login(request, user)
        return redirect(home_url_for(user))
    return render(request, "signup.html")


def admin_login_view(request):
    """/admin/login/ goes through the normal login page, so it gets the same attempt limits."""
    url = reverse("login")
    next_url = request.GET.get("next") or reverse("admin:index")
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        url += "?" + urlencode({"next": next_url})
    return redirect(url)


def logout_view(request):
    logout(request)
    return redirect("home")


@require_POST
def session_ping_view(request):
    """Called by idle-timeout.js every few minutes while a UEnvision tab is visible,
    so a user looking at the page counts as active. IdleTimeoutMiddleware does the rest."""
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "session_expired": True}, status=401)
    return JsonResponse({"ok": True})


def verify_email_view(request, uidb64, token):
    user = email_verification.user_from_link(uidb64, token)
    if user is None:
        return render(request, "verify_email.html", {"state": "invalid"})
    user.email_verified = True
    user.save(update_fields=["email_verified"])
    return render(request, "verify_email.html", {"state": "confirmed"})


@login_required
@require_POST
def send_my_verification_view(request):
    """The "Send the confirmation link" button on the student dashboard and in Settings."""
    user = request.user
    next_url = request.POST.get("next") or ""
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse("settings")
    if user.email_verified:
        messages.success(request, "Your email is already confirmed.")
    elif not email_verification.can_resend(user.email):
        messages.error(request, "We just sent you a link. Please wait a minute before asking for another one.")
    elif email_verification.send_verification_email(request, user):
        messages.success(request, f"We sent a confirmation link to {user.email}. Check your spam or junk folder too.")
    else:
        messages.error(request, "We couldn't send the email just now. Please try again in a minute.")
    return redirect(next_url)


@login_required
def pending_approval_view(request):
    # Faculty no longer wait for approval to use UEnvision; old links land on their home page.
    return redirect(home_url_for(request.user))


@require_POST
def resend_verification_view(request):
    email = (request.POST.get("email") or "").strip()
    ctx = {"state": "resent", "email": email}
    if not email:
        return render(request, "verify_email.html", {"state": "invalid"})
    if not email_verification.can_resend(email):
        return render(request, "verify_email.html", {**ctx, "wait": True})
    user = CustomUser.objects.filter(email__iexact=email, email_verified=False, is_active=True).first()
    if user is not None:
        email_verification.send_verification_email(request, user)
    # Same answer whether or not the account exists, so this can't be used to look up emails.
    return render(request, "verify_email.html", ctx)


def forgot_password_view(request):
    if request.method != "POST":
        return render(request, "forgot_password.html")
    email = (request.POST.get("email") or "").strip()
    try:
        validate_email(email)
    except ValidationError:
        return render(request, "forgot_password.html", {"error": "Enter a valid email address.", "email": email})
    if email_verification.reset_rate_limited(email):
        return render(request, "forgot_password.html", {"sent": True, "email": email, "wait": True})
    user = CustomUser.objects.filter(email__iexact=email, is_active=True).first()
    if user is not None:
        email_verification.send_password_reset_email(request, user)
    # Same answer whether or not the account exists, so this can't be used to look up emails.
    return render(request, "forgot_password.html", {"sent": True, "email": email})


def reset_password_view(request):
    """Old address of the reset page; the real one comes from the emailed link."""
    return redirect("forgot_password")


def reset_password_confirm_view(request, uidb64, token):
    user = email_verification.reset_user_from_link(uidb64, token)
    if user is None:
        return render(request, "reset_password.html", {"invalid": True})
    ctx = {"min_password_length": MIN_PASSWORD_LENGTH, "email": user.email}
    if request.method != "POST":
        return render(request, "reset_password.html", ctx)
    new = request.POST.get("password", "")
    confirm = request.POST.get("password2", "")
    if len(new) < MIN_PASSWORD_LENGTH:
        return render(request, "reset_password.html", {**ctx, "error": f"Password must be at least {MIN_PASSWORD_LENGTH} characters."})
    if new != confirm:
        return render(request, "reset_password.html", {**ctx, "error": "Passwords do not match."})
    user.set_password(new)
    user.email_verified = True  # they opened a link sent to this address
    user.must_change_password = False  # they just chose their own
    user.save(update_fields=["password", "email_verified", "must_change_password"])
    login_limits.clear_email(user.email)  # a locked-out user who reset their password can log in right away
    return render(request, "reset_password.html", {"done": True})


@login_required
def dashboard_view(request):
    from .student_views import latest_response

    feedback_nudge.record_use(request.user)
    return render(request, "dashboard.html", {"active_page": "dashboard",
                                              "has_professor_record": latest_response(request.user) is not None})


@login_required
def dashboard_skills_view(request):
    """JSON for the dashboard's top-skills bar chart, skills-per-month line chart,
    and (added alongside the existing two) the skill gap analysis against the
    curriculum surveys — see gap_analysis.py for exactly what that compares."""
    try:
        top = int(request.GET.get("top", 10))
        months = int(request.GET.get("months", 0))
    except ValueError:
        return JsonResponse({"ok": False, "error": "Bad number."}, status=400)
    if not 1 <= top <= 30 or not 0 <= months <= 600:
        return JsonResponse({"ok": False, "error": "Top must be 1-30."}, status=400)
    pipeline.ensure_skill_csvs()
    source = request.GET.get("source", "")
    level = request.GET.get("level", "")
    program = request.GET.get("program", "")
    if program and program not in curriculum_data.PROGRAMS:
        return JsonResponse({"ok": False, "error": "Unknown program."}, status=400)
    try:
        data = pipeline.skills_dashboard(request.GET.get("kind", "hard"), top, source, level, months, program)
    except (OSError, UnicodeDecodeError) as exc:
        return JsonResponse({"ok": False, "error": f"Couldn't read the data: {exc}"}, status=500)
    if data.get("exists"):
        try:
            data["gap"] = gap_analysis.compute(top, source, level, program, dummy=_sees_dummy_results(request))
        except (OSError, UnicodeDecodeError) as exc:
            data["gap"] = {"exists": False, "error": str(exc)}
    return JsonResponse({"ok": True, **data})


def _subject_choices():
    """[(code, label)] for every subject professors teach, once per code (subjects
    that BSIT and BSCS share are listed once; practicum/research/capstone and the
    placeholder Professional Electives are left out)."""
    tags = curriculum_data.subject_term_tags()
    subjects = sorted(curriculum_data.subject_by_code().items(),
                      key=lambda item: curriculum_data.subject_sort_key(item[0], tags))
    return [(code, f"{code} — {info['name']}") for code, info in subjects
            if code not in curriculum_data.HIDDEN_FROM_PROFESSORS]


def _subject_code(value):
    """Subject code from a ?subject= value; also accepts the older "PROGRAM|CODE" form."""
    return str(value or "").split("|")[-1]


def _my_custom_subjects(user):
    """{code: {"name", "programs", "term_label"}} for the subjects this professor added
    themselves because they aren't in the curriculum list (e.g. an elective)."""
    from .student_views import latest_response

    latest = latest_response(user)
    out = {}
    for subj in ((latest.data or {}).get("subjects") or []) if latest else []:
        if isinstance(subj, dict) and subj.get("custom") and subj.get("code"):
            out[str(subj["code"])] = {"name": str(subj.get("name") or ""), "programs": subj.get("programs") or [],
                                      "term_label": "Added by you"}
    return out


def _my_subjects(user):
    """Subjects in this professor's current record (latest Professor Survey response,
    possibly edited on Data -> My subjects & skills), including ones they added."""
    from .student_views import latest_response

    seen, out = set(), []
    labels = dict(_subject_choices())
    labels.update({code: f"{code} — {info['name']}" for code, info in _my_custom_subjects(user).items()})
    latest = latest_response(user)
    for data in ([latest.data] if latest else []):
        for subj in (data or {}).get("subjects") or []:
            value = str(subj.get("code") or "")
            if value in labels and value not in seen:
                seen.add(value)
                out.append((value, labels[value]))
    return out


@login_required
def recommendations_view(request):
    """Professor recommendations. Two views of the same page:
    * no subject chosen: the ranked under-taught-skills list (reusing
      gap_analysis.py — same list the Dashboard's Skill Gap Analysis tab shows);
    * ?subject=CODE: in-demand skills that fit that subject, ranked by
      demand minus how deeply the Professor Survey says they're already taught
      there (gap_analysis.subject_targets).
    Either way, already generated Gemini resources are shown. Generating more is a
    separate POST (recommendations_generate_view) so simply opening this page never
    spends API quota."""
    feedback_nudge.record_use(request.user)
    cached = recommendations.load_recommendations()
    subject_value = _subject_code(request.GET.get("subject", ""))
    choices = _subject_choices()
    custom = _my_custom_subjects(request.user)
    subject = None
    dummy = _sees_dummy_results(request)
    gap = gap_analysis.compute(top=10, dummy=dummy)
    if subject_value in dict(choices) or subject_value in custom:
        subject = gap_analysis.subject_targets(subject_value, info=custom.get(subject_value), dummy=dummy)
        rows = list(subject.get("targets") or []) if subject.get("exists") else []
    else:
        subject_value = ""
        rows = list(gap.get("under_taught") or []) if gap.get("exists") else []
    for row in rows:
        row["cached_resources"] = cached.get(row["skill"].strip().lower(), [])
    return render(request, "recommendations.html", {
        "active_page": "recommendations",
        "gap": gap,
        "under_taught": rows,
        "subject": subject,
        "subject_value": subject_value,
        "subject_choices": choices,
        "my_subjects": _my_subjects(request.user),
        "has_any_recommendations": bool(cached),
        "max_per_run": recommendations.MAX_SKILLS_PER_RUN,
        "default_photo": recommendations.DEFAULT_PHOTO,
    })


@login_required
@require_POST
def recommendations_generate_view(request):
    skills = [s.strip() for s in request.POST.getlist("skills") if s and s.strip()]
    skills = skills[:recommendations.MAX_SKILLS_PER_RUN]
    if not skills:
        return JsonResponse({"ok": False, "error": "Choose at least one skill."}, status=400)
    context = ""
    subject_value = _subject_code(request.POST.get("subject", ""))
    labels = dict(_subject_choices())
    labels.update(_my_subjects(request.user))
    if subject_value in labels:
        context = f"to teach within the university subject {labels[subject_value]}"
    try:
        out = recommendations.generate_for_skills(skills, "professor", context)
    except recommendations.RecommendationError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse({"ok": True, **out})


@login_required
def recommendations_download_view(request):
    path = recommendations.recs_path()
    if not path.is_file():
        raise Http404("No recommendations have been generated yet.")
    return FileResponse(open(path, "rb"), as_attachment=True, filename=path.name, content_type="text/csv")


@login_required
def feedback_view(request):
    return render(request, "feedback.html", {"active_page": "feedback"})


@login_required
@require_POST
def feedback_later_view(request):
    """The banner's "Later" button: hide it for a few days, then go back to the same page."""
    feedback_nudge.snooze(request.user)
    nxt = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        nxt = reverse("student_dashboard" if request.user.is_learner else "dashboard")
    return redirect(nxt)


@login_required
def help_view(request):
    # Developers test every role, so they see every section.
    idle_minutes = getattr(django_settings, "IDLE_TIMEOUT_SECONDS", 1800) // 60
    return render(request, "help.html", {"active_page": "help", "show_all": request.user.is_developer,
                                         "idle_minutes": idle_minutes})


@login_required
def about_view(request):
    return render(request, "about.html", {"active_page": "about"})


@login_required
def settings_view(request):
    return render(request, "settings.html", {"active_page": "settings", "min_password_length": MIN_PASSWORD_LENGTH,
                                             "edit_account": request.GET.get("edit") == "1"})


@login_required
@require_POST
def update_account_view(request):
    """Settings > Account settings: change your own name and email."""
    user = request.user
    data, error = _clean_account_fields(request.POST, exclude_pk=user.pk)
    if not error and user.is_learner and not _is_ue_email(data["email"]):
        error = f"Please use your UE email address (ending in @{UE_EMAIL_DOMAIN})."
    if error:
        messages.error(request, error)
        return redirect(reverse("settings") + "?edit=1")
    email_changed = data["email"].lower() != user.email.lower()
    for field, value in data.items():
        setattr(user, field, value)
    fields = list(data)
    # Students and alumni confirm a new email; faculty and staff don't need to.
    needs_link = email_changed and user.is_learner and email_verification.verification_required()
    if email_changed:
        user.email_verified = not needs_link
        fields.append("email_verified")
    user.save(update_fields=fields)
    if needs_link and email_verification.send_verification_email(request, user):
        messages.success(request, f"Saved. We sent a confirmation link to {user.email}.")
    elif needs_link:
        messages.success(request, "Saved. We couldn't send the confirmation email just now, so use "
                                  "\u201cSend confirmation link\u201d next to your email in a minute.")
    else:
        messages.success(request, "Your account details were saved.")
    return redirect("settings")


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
        was_temporary = request.user.must_change_password
        request.user.set_password(new)
        request.user.must_change_password = False
        request.user.save(update_fields=["password", "must_change_password"])
        update_session_auth_hash(request, request.user)  # keep this session logged in
        messages.success(request, "Your password has been changed.")
        if was_temporary:
            return redirect(home_url_for(request.user))
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


# Account types offered on the Accounts page: the roles (Developer included) plus the two dummy
# (test) types, which are a student / faculty role with is_dummy set.
ACCOUNT_TYPES = [
    *CustomUser.Role.choices,
    ("dummy_student", "Dummy Student"),
    ("dummy_faculty", "Dummy Faculty"),
]
DUMMY_TYPES = {"dummy_student": CustomUser.Role.STUDENT, "dummy_faculty": CustomUser.Role.FACULTY}


# Filters on the Accounts page: (value, label, queryset filter)
ACCOUNT_FILTERS = [
    ("", "All accounts", {}),
    ("pending", "Not approved yet", {"is_approved": False}),
    ("administrator", "Administrators", {"role": CustomUser.Role.ADMINISTRATOR}),
    ("developer", "Developers", {"role": CustomUser.Role.DEVELOPER}),
    ("faculty", "Faculty", {"role": CustomUser.Role.FACULTY, "is_dummy": False}),
    ("student", "Students", {"role": CustomUser.Role.STUDENT, "is_dummy": False}),
    ("alumni", "Alumni", {"role": CustomUser.Role.ALUMNI, "is_dummy": False}),
    ("dummy", "Dummy (test) accounts", {"is_dummy": True}),
]


# Sort options on the Accounts page: value -> (label, order_by fields)
ACCOUNT_SORTS = {
    "": ("Not approved yet first", ("is_approved", "last_name", "first_name")),
    "name": ("Name (A–Z)", ("last_name", "first_name")),
    "-name": ("Name (Z–A)", ("-last_name", "-first_name")),
    "-joined": ("Newest first", ("-date_joined", "-pk")),
    "joined": ("Oldest first", ("date_joined", "pk")),
    "role": ("Role", ("role", "is_dummy", "last_name", "first_name")),
    "email": ("Email", ("email",)),
}


@administrator_required
def accounts_view(request):
    from django.db.models import Q

    status = request.GET.get("status", "")
    filters = {value: f for value, _, f in ACCOUNT_FILTERS}
    if status not in filters:
        status = ""
    q = request.GET.get("q", "").strip()
    accounts = CustomUser.objects.filter(**filters[status])
    for word in q.split():
        accounts = accounts.filter(Q(first_name__icontains=word) | Q(last_name__icontains=word) |
                                   Q(middle_name__icontains=word) | Q(email__icontains=word))
    sort = request.GET.get("sort", "")
    if sort not in ACCOUNT_SORTS:
        sort = ""
    accounts = accounts.order_by(*ACCOUNT_SORTS[sort][1])
    return render(request, "accounts.html", {
        "active_page": "accounts",
        "accounts": accounts,
        "q": q,
        "status": status,
        "status_choices": [(v, label) for v, label, _ in ACCOUNT_FILTERS],
        "sort": sort,
        "sort_choices": [(v, label) for v, (label, _) in ACCOUNT_SORTS.items()],
        "pending_count": CustomUser.objects.filter(is_approved=False).count(),
        "total_count": CustomUser.objects.count(),
        "roles": ACCOUNT_TYPES,
        "min_password_length": MIN_PASSWORD_LENGTH,
    })


@administrator_required
@require_POST
def account_create_view(request):
    data, error = _clean_account_fields(request.POST)
    role = request.POST.get("role", CustomUser.Role.FACULTY)
    typed = request.POST.get("password", "")
    password = typed or make_temporary_password()  # blank -> a one-time password shown below
    is_dummy = role in DUMMY_TYPES
    role = DUMMY_TYPES.get(role, role)

    if not error and role not in CustomUser.Role.values:
        error = "Choose a valid role."
    if not error and len(password) < MIN_PASSWORD_LENGTH:
        error = f"Password must be at least {MIN_PASSWORD_LENGTH} characters."

    if error:
        messages.error(request, error)
    else:
        user = CustomUser.objects.create_user(password=password, role=role, is_dummy=is_dummy,
                                              must_change_password=not typed, **data)
        if typed:
            messages.success(request, f"Account created for {data['email']}.")
        elif notifications.send_temporary_password(request, user, password, new_account=True):
            messages.success(request, f"Account created for {data['email']}. A temporary password was emailed to "
                                      "them; they will choose their own the first time they log in.")
        else:
            messages.success(request, f"Account created for {data['email']}, but the email couldn't be sent. "
                                      f"Temporary password: {password} — give it to them yourself; it won't be "
                                      "shown again. They will choose their own the first time they log in.")
    return redirect("accounts")


@administrator_required
@require_POST
def account_edit_view(request, pk):
    target = get_object_or_404(CustomUser, pk=pk)
    data, error = _clean_account_fields(request.POST, exclude_pk=target.pk)
    account_type = request.POST.get("account_type") or _account_type(target)
    if not error and account_type not in dict(ACCOUNT_TYPES):
        error = "Choose a valid role."
    if not error and target.pk == request.user.pk and account_type != _account_type(target):
        # so an administrator can't lock themselves (or the last administrator) out
        error = "You can't change your own role. Ask another administrator."
    if error:
        messages.error(request, error)
        return redirect(request.POST.get("next") or "accounts")
    for field, value in data.items():
        setattr(target, field, value)
    notes = []
    old_label = target.role_label
    answers_were_dummy = target.answers_are_dummy
    role = DUMMY_TYPES.get(account_type, account_type)
    is_dummy = account_type in DUMMY_TYPES
    if role != target.role:
        target.role = role
        data["role"] = role
    if is_dummy != target.is_dummy:
        target.is_dummy = is_dummy
        data["is_dummy"] = is_dummy
    if target.answers_are_dummy != answers_were_dummy:
        # Their answers so far move with them (to or from a dummy type or Developer),
        # so the real results stay clean.
        dummy_now = target.answers_are_dummy
        moved = target.curriculum_survey_responses.update(is_dummy=dummy_now)
        target.survey_responses.update(is_dummy=dummy_now)
        where = "dummy (test) data" if dummy_now else "the real results"
        if moved:
            notes.append(f"{moved} survey answer{'' if moved == 1 else 's'} moved to {where}.")
    if target.role_label != old_label:
        notes.insert(0, f"Role changed from {old_label} to {target.role_label}.")
    target.save(update_fields=list(data))
    messages.success(request, " ".join([f"Account updated for {target.email}."] + notes))
    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("accounts")


def _account_type(user):
    """The Accounts page's type value for a user, e.g. "faculty" or "dummy_faculty"."""
    return f"dummy_{user.role}" if user.is_dummy else user.role


@administrator_required
@require_POST
def account_approve_view(request, pk):
    target = get_object_or_404(CustomUser, pk=pk)
    if not target.is_approved:
        target.is_approved = True
        target.save(update_fields=["is_approved"])
        notifications.mark_read_about(target)
        messages.success(request, f"Approved {target.get_full_name()} ({target.email}).")
    return redirect(request.POST.get("next") if url_has_allowed_host_and_scheme(
        request.POST.get("next"), allowed_hosts={request.get_host()}) else "accounts")


@administrator_required
def notifications_view(request):  # "See all notifications" from the bell
    items = list(Notification.objects.filter(recipient=request.user).select_related("subject_user")[:100])
    unread_ids = [n.pk for n in items if n.read_at is None]
    response = render(request, "notifications.html", {"active_page": "notifications", "items": items,
                                                      "unread_ids": set(unread_ids)})
    # Opening the page counts as reading them (the badge clears on the next page).
    Notification.objects.filter(pk__in=unread_ids).update(read_at=timezone.now())
    return response


@administrator_required
@require_POST
def notifications_read_view(request):
    """Opening the bell's dropdown marks everything as read (clears the red count)."""
    Notification.objects.filter(recipient=request.user, read_at__isnull=True).update(read_at=timezone.now())
    return JsonResponse({"ok": True})


@administrator_required
@require_GET
def notifications_poll_view(request):
    """The bell asks for this every few seconds so new notifications show up without a refresh.
    `page` is the page the bell is on, so the dropdown's Approve button returns there."""
    page = request.GET.get("page", "")
    if not url_has_allowed_host_and_scheme(page, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        page = reverse("dashboard")
    html = render_to_string("_notif_panel_body.html", {"notif_next": page}, request=request)
    return JsonResponse({"unread": notifications.unread_count(request.user), "html": html})


@administrator_required
@require_POST
def notification_settings_view(request):
    request.user.notify_by_email = request.POST.get("notify_by_email") == "1"
    request.user.save(update_fields=["notify_by_email"])
    state = "on" if request.user.notify_by_email else "off"
    messages.success(request, f"Email alerts are {state}.")
    return redirect("settings")


@administrator_required
@require_POST
def account_reset_password_view(request, pk):
    target = get_object_or_404(CustomUser, pk=pk)
    password = make_temporary_password()
    target.set_password(password)
    target.must_change_password = True
    target.save(update_fields=["password", "must_change_password"])
    if target.pk == request.user.pk:
        update_session_auth_hash(request, target)  # `target` holds the new hash; request.user is stale
    if target.pk != request.user.pk and notifications.send_temporary_password(request, target, password):
        messages.success(request, f"Password for {target.email} was reset and a temporary password was emailed to "
                                  "them. They will choose their own when they log in.")
    elif target.pk == request.user.pk:
        messages.success(request, f"Your password was reset. Temporary password: {password} — choose your own "
                                  "password below now.")
    else:
        messages.success(request, f"Password for {target.email} was reset, but the email couldn't be sent. "
                                  f"Temporary password: {password} — give it to them yourself; it won't be shown "
                                  "again. They will choose their own when they log in.")
    return redirect("accounts")


@administrator_required
@require_POST
def account_delete_view(request, pk):
    target = get_object_or_404(CustomUser, pk=pk)
    if target.pk == request.user.pk:
        messages.error(request, "You can't remove your own account from here.")
    else:
        email = target.email
        if not target.is_approved:
            # A sign-up that was never approved isn't real faculty: their answers go too.
            SurveyResponse.objects.filter(user=target).delete()
            CurriculumSurveyResponse.objects.filter(user=target).delete()
            target.delete()
            messages.success(request, f"Account {email} and its survey answers were removed.")
        else:
            target.delete()
            messages.success(request, f"Account {email} was removed.")
    return redirect("accounts")


# ---------------------------------------------------------------------------
# Feedback surveys (SUS / UAT / functional test sheet) — called by survey.js
# ---------------------------------------------------------------------------
MAX_SURVEY_ROWS = 200
# 3 = the 6-statement, all-positive, plain-English SUS (every item scores answer - 1).
# Responses saved before it used the 10-item SUS (no "sus_version" = standard alternating,
# 2 = all-positive), so keep the versions apart when averaging.
SUS_VERSION = 3
SUS_QUESTION_COUNT = 6  # must match SUS_QUESTIONS in survey.js


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
    if request.user.is_learner and kind != SurveyResponse.SUS:
        return JsonResponse({"ok": False, "error": "Students and alumni can only answer the SUS survey."}, status=403)

    if kind == SurveyResponse.SUS:
        for row in rows:
            answers = [row.get(f"q{n}") for n in range(1, SUS_QUESTION_COUNT + 1)]
            if not all(isinstance(a, int) and not isinstance(a, bool) and 1 <= a <= 5 for a in answers):
                return JsonResponse({"ok": False, "error": "SUS answers must be 1-5."}, status=400)
            row["sus_score"] = _compute_sus_score(answers)  # never trust the client's score
            row["sus_version"] = SUS_VERSION

    # Who answered comes from the account, not from the form.
    name, role = request.user.get_full_name(), request.user.role_label
    for row in rows:
        if kind == SurveyResponse.SUS:
            row["respondent_name"], row["respondent_role"] = name, role
        else:
            row["tester_name"], row["tester_role"] = name, role

    SurveyResponse.objects.bulk_create(
        [SurveyResponse(survey_type=kind, user=request.user, data=row, is_dummy=request.user.answers_are_dummy) for row in rows]
    )
    return JsonResponse({"ok": True, "saved": len(rows)})


# ---------------------------------------------------------------------------
# Data  (four separate pages: View Data / Import Data / Scrape Data / Extract Skills)
# View Data is open to every logged-in user. Import, Scrape and Extract Skills change files on the
# server (and Scrape spends API quota / makes outbound requests), so they are
# Administrator-only.
# ---------------------------------------------------------------------------
def _data_ctx(request, tab, **extra):
    return {"active_page": "data", "data_tab": tab, **extra}


@login_required
def data_view(request):
    summary = pipeline.disk_summary()
    tables = []
    pipeline.ensure_skill_csvs()
    for key, (label, _fn) in pipeline.TABLES.items():
        if key in pipeline.SOURCES:
            info = summary["sources"][key]["compiled"]
        else:
            info = pipeline._file_info(pipeline.table_path(key))
        tables.append({"key": key, "label": label, "exists": info["exists"],
                       "delete_note": pipeline.DELETABLE_TABLES.get(key, "")})
    default = next((t["key"] for t in tables if t["exists"]), tables[0]["key"])
    if request.GET.get("source") in pipeline.TABLES:
        default = request.GET["source"]
    return render(request, "data_view.html", _data_ctx(request, "view", tables=tables, default_table=default))


@administrator_required
@require_POST
def data_delete_view(request, key):
    if key not in pipeline.TABLES:
        raise Http404
    label = pipeline.TABLES[key][0]
    error = pipeline.delete_table(key)
    if error:
        messages.error(request, error)
    else:
        messages.success(request, f"Deleted {label}.")
    return redirect(reverse("data") + "?" + urlencode({"source": key}))


@login_required
def data_table_view(request):
    key = request.GET.get("source", "")
    if key not in pipeline.TABLES:
        return JsonResponse({"ok": False, "error": "Unknown data source."}, status=400)
    try:
        page = int(request.GET.get("page", 1))
        size = int(request.GET.get("page_size", 50))
    except ValueError:
        return JsonResponse({"ok": False, "error": "Bad paging values."}, status=400)
    try:
        data = pipeline.query_table(key, request.GET.get("q", ""), page, size)
    except (OSError, UnicodeDecodeError) as exc:
        return JsonResponse({"ok": False, "error": f"Couldn't read that file: {exc}"}, status=500)
    return JsonResponse({"ok": True, **data})


@login_required
def data_download_view(request, key):
    if key not in pipeline.TABLES:
        raise Http404
    path = pipeline.table_path(key)
    if not path.is_file():
        raise Http404("That file doesn't exist yet.")
    return FileResponse(open(path, "rb"), as_attachment=True, filename=path.name, content_type="text/csv")


@administrator_required
def data_import_view(request):
    if request.method == "POST":
        kind = request.POST.get("import_type", "")
        files = request.FILES.getlist("files")
        if kind not in pipeline.IMPORT_TYPES:
            messages.error(request, "Choose what you are importing.")
            return redirect("data_import")
        if not files:
            messages.error(request, "Choose at least one file to import.")
            return redirect("data_import")
        label, fmt, target = pipeline.IMPORT_TYPES[kind]

        if fmt == "json":
            res = pipeline.import_json_files(target, files, overwrite=request.POST.get("mode") == "replace")
            for err in res["errors"]:
                messages.error(request, err)
            if res["added"] or res["existing"]:
                msg = f"{label}: {res['added']} file(s) added to data/jsons/{target}/"
                if res["existing"]:
                    msg += f", {res['existing']} already existed (skipped)"
                if res["invalid"]:
                    msg += f", {res['invalid']} didn't look like {pipeline.SOURCE_LABELS[target]} job files (ignored)"
                messages.success(request, msg + ".")
                if res["added"] and request.POST.get("compile_after") == "on":
                    ok, last = pipeline.compile_now(target)
                    if ok:
                        messages.success(request, f"Rebuilt data/compiled_{target}.csv from the JSON files.")
                    else:
                        messages.error(request, f"Imported, but compiling failed: {last}")
            elif not res["errors"]:
                messages.error(request, f"None of those files looked like {pipeline.SOURCE_LABELS[target]} job JSONs.")
        else:
            if len(files) > 1:
                messages.error(request, "Import one CSV at a time.")
                return redirect("data_import")
            try:
                res = pipeline.import_csv(target, files[0], merge=request.POST.get("mode") != "replace")
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    f"{label}: {res['added']} row(s) added, {res['skipped']} skipped (duplicate or missing job_id); "
                    f"{res['total']} row(s) now in {pipeline.table_path(target).name}.")
        return redirect("data_import")

    return render(request, "data_import.html", _data_ctx(
        request, "import", summary=pipeline.disk_summary(), import_types=pipeline.IMPORT_TYPES))


def _scrape_ctx(request, form=None):
    return _data_ctx(
        request, "scrape",
        form=form or pipeline.get_scrape_settings(),
        run=pipeline.get_run_state(),
        summary=pipeline.disk_summary(),
    )


def _extract_ctx(request, form=None):
    summary = pipeline.disk_summary()
    return _data_ctx(
        request, "extract",
        form=form or pipeline.get_extract_settings(),
        run=pipeline.get_run_state(),
        summary=summary,
        keys_text=pipeline.read_api_keys_text(),
        key_count=pipeline.count_api_keys(),
        max_batch=pipeline.MAX_BATCH_SIZE,
        default_model=pipeline.DEFAULT_MODEL,
    )


@administrator_required
def data_scrape_view(request):
    return render(request, "data_scrape.html", _scrape_ctx(request))


@administrator_required
@require_POST
def scrape_run_view(request):
    cfg, error = pipeline.parse_scrape_form(request.POST)
    if not error:
        start_error = pipeline.start_run(cfg, kind="scrape")
        if start_error:      # a problem with the run itself goes in the Console, not on the form
            pipeline.log_to_console(start_error)
            return redirect("console")
    if error:
        messages.error(request, error)
        return render(request, "data_scrape.html", _scrape_ctx(request, form=cfg))
    pipeline.save_scrape_settings(cfg)
    return redirect("console")


@administrator_required
def data_extract_view(request):
    return render(request, "data_extract.html", _extract_ctx(request))


@administrator_required
@require_POST
def extract_run_view(request):
    cfg, error = pipeline.parse_extract_form(request.POST)
    if not error:
        start_error = pipeline.start_run(cfg, kind="extract")
        if start_error:
            pipeline.log_to_console(start_error)
            return redirect("console")
    if error:
        messages.error(request, error)
        return render(request, "data_extract.html", _extract_ctx(request, form=cfg))
    pipeline.save_extract_settings(cfg)
    return redirect("console")


def _stop_and_redirect(request, target):
    # The outcome is written to the run log, so it shows in the Console either way.
    pipeline.stop_run()
    return redirect("console")


@administrator_required
@require_POST
def scrape_stop_view(request):
    return _stop_and_redirect(request, "data_scrape")


@administrator_required
@require_POST
def extract_stop_view(request):
    return _stop_and_redirect(request, "data_extract")


@administrator_required
def console_view(request):
    """Live status and log of the scrape / extract run (Administrator only)."""
    return render(request, "console.html", {"active_page": "console", "run": pipeline.get_run_state()})


@administrator_required
@require_POST
def console_stop_view(request):
    return _stop_and_redirect(request, "console")


@administrator_required
def scrape_status_view(request):
    st = pipeline.get_run_state()
    return JsonResponse({
        "status": st.get("status", "idle"),
        "kind": st.get("kind"),
        "current": st.get("current"),
        "steps": st.get("steps", []),
        "source": st.get("source"),
        "started_at": st.get("started_at"),
        "finished_at": st.get("finished_at"),
        "error": st.get("error"),
        "log": pipeline.read_log_tail(),
        "summary": pipeline.disk_summary(),
    })


@administrator_required
@require_POST
def api_keys_save_view(request):
    error = pipeline.save_api_keys_text(request.POST.get("keys", ""))
    if error:
        messages.error(request, error)
    else:
        n = pipeline.count_api_keys()
        messages.success(request, f"api_keys.txt saved ({n} key{'s' if n != 1 else ''}).")
    return redirect("data_extract")


# ---------------------------------------------------------------------------
# Curriculum-mapping surveys (Student / Fresh Grad Alumni / Professor)
#
# Public (no login required) — these are filled out by outside respondents,
# not app users. Each one is a single page: pick your program/year (or, for
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


def _sees_dummy_results(request):
    """Dummy accounts always see results computed from dummy answers. Developers see the
    real results unless they've flipped the Real / Dummy switch to Dummy."""
    from .context_processors import DEV_DUMMY_VIEW_KEY
    user = request.user
    return user.is_dummy or (user.is_developer and bool(request.session.get(DEV_DUMMY_VIEW_KEY)))


@administrator_required
@require_POST
def developer_results_view(request):
    """The Real / Dummy results switch (developers only)."""
    from .context_processors import DEV_DUMMY_VIEW_KEY
    if not request.user.is_developer:
        raise PermissionDenied
    request.session[DEV_DUMMY_VIEW_KEY] = request.POST.get("results") == "dummy"
    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect("dashboard")


def _is_dummy(request):
    """Answers sent while logged in as a dummy (test) account or a developer go to the dummy data set."""
    return request.user.is_authenticated and request.user.answers_are_dummy


def _learner_survey_saved(request, response):
    """After a student/alumni survey: a logged-in student/alumni is linked right
    away; anyone else gets a signed link to register and see their results."""
    from . import student_views

    user = request.user
    if user.is_authenticated and user.is_learner:
        response.user = user
        response.save(update_fields=["user"])
        return JsonResponse({"ok": True, "next_url": reverse("student_dashboard")})
    return JsonResponse({"ok": True, "register_url": student_views.register_url_for(response)})


def _clean_target_role(payload):
    from . import job_roles

    role = payload.get("target_role")
    payload["target_role"] = role if role in job_roles.ROLE_LABELS else ""


def _ue_email_error(payload):
    if not _is_ue_email(str(payload["personal_info"].get("ue_email") or "").strip()):
        return f"Please use your UE email address (ending in @{UE_EMAIL_DOMAIN})."
    return None


@require_POST
def student_survey_submit_view(request):
    payload, error = _parse_curriculum_submission(request)
    if error:
        return JsonResponse({"ok": False, "error": error}, status=400)
    error = _ue_email_error(payload)
    if error:
        return JsonResponse({"ok": False, "error": error}, status=400)
    terms = {s.get("term") for s in payload["subjects"] if isinstance(s, dict)}
    if "current" not in terms:
        return JsonResponse({"ok": False, "error": "Please select at least one current-semester subject."}, status=400)
    if payload.get("has_previous") and "previous" not in terms:
        return JsonResponse({"ok": False, "error": "Please select at least one previous-semester subject."}, status=400)
    _clean_target_role(payload)
    response = _save_curriculum_survey(CurriculumSurveyResponse.STUDENT, payload, dummy=_is_dummy(request))
    return _learner_survey_saved(request, response)


@require_POST
def alumni_survey_submit_view(request):
    payload, error = _parse_curriculum_submission(request)
    if error:
        return JsonResponse({"ok": False, "error": error}, status=400)
    error = _ue_email_error(payload)
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
    from .student_views import latest_response

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


def _safe_json(obj):
    """mark_safe()'d JSON for embedding in a <script type="application/json">
    tag — escapes "</" so nothing in the data can break out of the tag."""
    return mark_safe(json.dumps(obj).replace("</", "<\\/"))


def student_survey_view(request):
    period = curriculum_data.current_period()
    bootstrap = {
        "programLabels": curriculum_data.PROGRAM_LABELS,
        "yearLevels": curriculum_data.YEAR_LEVELS,
        "currentSemLabel": period["current_label"],
        "ueEmailDomain": UE_EMAIL_DOMAIN,
        "eligibility": curriculum_data.build_student_eligibility(period["slot"]),
        "targetRole": request.GET.get("role", ""),
        "skills": ontology.subject_skill_map(),
        "termTags": curriculum_data.subject_term_tags(),
        "submitUrl": reverse("student_survey_submit"),
        "skillSearchUrl": reverse("skill_search"),
        "skillAddUrl": reverse("skill_add"),
    }
    return render(request, "student_survey.html", {
        "is_placeholder_curriculum": curriculum_data.CURRICULUM_IS_PLACEHOLDER,
        "bootstrap_json": _safe_json(bootstrap),
    })


def alumni_survey_view(request):
    terms_by_program = {
        program: curriculum_data.term_sequence(program)
        for program in curriculum_data.PROGRAMS
    }
    bootstrap = {
        "programLabels": curriculum_data.PROGRAM_LABELS,
        "termsByProgram": terms_by_program,
        "subjectsByProgramTerm": curriculum_data.SUBJECTS,
        "targetRole": request.GET.get("role", ""),
        "ueEmailDomain": UE_EMAIL_DOMAIN,
        "skills": ontology.subject_skill_map(),
        "termTags": curriculum_data.subject_term_tags(),
        "submitUrl": reverse("alumni_survey_submit"),
        "skillSearchUrl": reverse("skill_search"),
        "skillAddUrl": reverse("skill_add"),
    }
    return render(request, "alumni_survey.html", {
        "is_placeholder_curriculum": curriculum_data.CURRICULUM_IS_PLACEHOLDER,
        "bootstrap_json": _safe_json(bootstrap),
    })


@login_required
def professor_survey_view(request):
    """The Professor Survey, which is also the professor's editable record: once
    answered, the page opens with their saved subjects and skills filled in."""
    from .student_views import latest_response

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
