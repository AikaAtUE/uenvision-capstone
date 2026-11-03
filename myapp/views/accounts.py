

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from ..models import (CustomUser, Notification, SurveyResponse, CurriculumSurveyResponse, MIN_PASSWORD_LENGTH,
                     make_temporary_password)
from .. import notifications
from .common import administrator_required


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
