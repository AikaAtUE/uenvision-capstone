from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import MIN_PASSWORD_LENGTH, ProfilePhoto
from .. import email_verification
from .accounts import _clean_account_fields
from .common import home_url_for
from .surveys import UE_EMAIL_DOMAIN, _is_ue_email


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
