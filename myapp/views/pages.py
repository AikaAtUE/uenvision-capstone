from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import MIN_PASSWORD_LENGTH, ProfilePhoto
from .. import email_verification
from .accounts import _clean_account_fields
from .common import home_url_for


@login_required
def help_view(request):
    # Developers test every role, so they see every section.
    user = request.user
    idle_minutes = getattr(django_settings, "IDLE_TIMEOUT_SECONDS", 1800) // 60
    # "Replay the tour" links: each opens the page the tour runs on with ?tour=<name>.
    if user.is_learner:
        survey_url = reverse("alumni_survey" if user.role == user.Role.ALUMNI else "student_survey")
        results_url = reverse("student_dashboard")
    else:
        survey_url, results_url = reverse("professor_survey"), reverse("dashboard")
    tours = [("survey", "How to answer the survey", survey_url),
             ("results", "How to read your results" if user.is_learner else "How to use the Dashboard", results_url)]
    if user.is_administrator:
        tours.append(("extraction", "Data Extraction (administrators)", reverse("data_extraction")))
        tours.append(("accounts", "Accounts (administrators)", reverse("accounts")))
    return render(request, "help.html", {"active_page": "help", "show_all": user.is_developer,
                                         "idle_minutes": idle_minutes,
                                         "tours": [{"name": n, "label": l, "url": f"{u}?tour={n}"} for n, l, u in tours]})


@login_required
@require_POST
def tour_seen_view(request):
    """onboarding-tour.js posts here when a tour is finished or skipped, so it doesn't start
    again (on this or any other device). How to use can still replay it."""
    name = request.POST.get("tour", "")
    if name not in request.user.TOURS:
        return JsonResponse({"ok": False, "error": "Unknown tour."}, status=400)
    seen = request.user.seen_tours()
    if name not in seen:
        seen.append(name)
        request.user.tours_seen = seen
        request.user.save(update_fields=["tours_seen"])
    return JsonResponse({"ok": True, "seen": seen})


@login_required
def about_view(request):
    return render(request, "about.html", {"active_page": "about"})


@login_required
def settings_view(request):
    return render(request, "settings.html", {"active_page": "settings", "min_password_length": MIN_PASSWORD_LENGTH,
                                             "edit_account": request.GET.get("edit") == "1",
                                             "theme_choices": THEME_CHOICES})


THEME_CHOICES = [("light", "Light"), ("dark", "Dark"), ("system", "System")]


@login_required
@require_POST
def theme_save_view(request):
    """Settings > Appearance and the top-bar light/dark button: Light, Dark or System.
    theme.js posts it in the background (JSON back); without JavaScript the Settings form
    posts it and comes back to Settings."""
    theme = request.POST.get("theme", "")
    if theme not in request.user.THEMES:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "error": "Choose light, dark or system."}, status=400)
        messages.error(request, "Choose light, dark or system.")
        return redirect("settings")
    request.user.theme = theme
    request.user.save(update_fields=["theme"])
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "theme": theme})
    messages.success(request, "Appearance saved.")
    return redirect(reverse("settings") + "#appearance")


@login_required
@require_POST
def update_account_view(request):
    """Settings > Account settings: change your own name and email."""
    user = request.user
    data, error = _clean_account_fields(request.POST, exclude_pk=user.pk)
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

    # An account made with "Continue with Google" has no password yet (set_unusable_password),
    # so Settings asks it to set one without a current password.
    has_password = request.user.has_usable_password()
    if has_password and not request.user.check_password(current):
        messages.error(request, "Current password is incorrect.")
    elif len(new) < MIN_PASSWORD_LENGTH:
        messages.error(request, f"New password must be at least {MIN_PASSWORD_LENGTH} characters.")
    elif new != confirm:
        messages.error(request, "New password and confirmation do not match.")
    elif has_password and new == current:
        messages.error(request, "New password must be different from your current password.")
    else:
        was_temporary = request.user.must_change_password
        request.user.set_password(new)
        request.user.must_change_password = False
        request.user.save(update_fields=["password", "must_change_password"])
        update_session_auth_hash(request, request.user)  # keep this session logged in
        messages.success(request, "Your password has been changed." if has_password else
                         "Your password has been set. You can now also log in with your email and password.")
        if was_temporary:
            return redirect(home_url_for(request.user))
    return redirect("settings")


# ---------------------------------------------------------------------------
# Profile picture (Settings). profile-photo.js shrinks the picture in the browser to a
# small square JPEG before uploading, so these only check and store what arrives.
# ---------------------------------------------------------------------------
MAX_PHOTO_BYTES = 300_000
PHOTO_TYPES = {b"\xff\xd8\xff": "image/jpeg", b"\x89PNG\r\n\x1a\n": "image/png"}


def _photo_type(data):
    for magic, content_type in PHOTO_TYPES.items():
        if data.startswith(magic):
            return content_type
    return None


@login_required
@require_POST
def profile_photo_upload_view(request):
    user = request.user
    if request.POST.get("remove"):
        ProfilePhoto.objects.filter(user=user).delete()
        user.photo_updated = None
        user.save(update_fields=["photo_updated"])
        messages.success(request, "Your profile picture was removed.")
        return redirect("settings")
    upload = request.FILES.get("photo")
    if upload is None:
        messages.error(request, "Please choose a picture first.")
        return redirect("settings")
    if upload.size > MAX_PHOTO_BYTES:
        messages.error(request, "That picture is too large. Please choose a smaller one.")
        return redirect("settings")
    data = upload.read()
    content_type = _photo_type(data)
    if content_type is None:
        messages.error(request, "Please choose a JPEG or PNG picture.")
        return redirect("settings")
    ProfilePhoto.objects.update_or_create(user=user, defaults={"data": data, "content_type": content_type})
    user.photo_updated = timezone.now()
    user.save(update_fields=["photo_updated"])
    messages.success(request, "Your profile picture was updated.")
    return redirect("settings")


@login_required
def profile_photo_view(request, pk):
    """The picture itself. Anyone logged in may see it (it's shown next to the name)."""
    photo = ProfilePhoto.objects.filter(user_id=pk).first()
    if photo is None:
        raise Http404
    response = HttpResponse(bytes(photo.data), content_type=photo.content_type)
    # The URL carries ?v=<photo_updated>, so a new picture gets a new URL.
    response["Cache-Control"] = "private, max-age=31536000"
    return response
