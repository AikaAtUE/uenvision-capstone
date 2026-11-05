import logging
from urllib.parse import urlencode


from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from ..models import (CustomUser, MIN_PASSWORD_LENGTH)
from .. import email_verification, notifications
from .. import login_limits
from ..google_auth import google_enabled
from .common import home_url_for

log = logging.getLogger(__name__)


def login_view(request):
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")
        # login.html posts with fetch() so a failed attempt doesn't reload the page;
        # without JavaScript the form posts normally and the page is re-rendered.
        wants_json = request.headers.get("x-requested-with") == "XMLHttpRequest"

        def failed(error, status=200):
            if wants_json:
                return JsonResponse({"ok": False, "error": error}, status=status)
            # keep the typed email (never the password) so they only retype the password
            return render(request, "login.html", {"error": error, "email": email or "",
                                                  "google_enabled": google_enabled()}, status=status)

        wait = login_limits.blocked_for(request, email)
        if wait:
            return failed(login_limits.message(wait), status=429)
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
            if not (next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()})):
                next_url = home_url_for(user)
            if wants_json:
                return JsonResponse({"ok": True, "redirect": next_url})
            return redirect(next_url)
        return failed("Invalid email or password.")
    if request.user.is_authenticated:
        return redirect(home_url_for(request.user))
    return render(request, "login.html", {"timed_out": request.GET.get("timeout") == "1",
                                          "google_enabled": google_enabled()})


def google_cancelled_view(request):
    """They closed or cancelled Google's account chooser."""
    messages.info(request, "Google sign-in was cancelled. You can log in with your email and password instead.")
    return redirect("login")


def google_error_view(request):
    messages.error(request, "Google sign-in didn't work just now. Please try again, or log in with your email and password.")
    return redirect("login")


SIGNUP_KINDS = ("student", "alumni", "faculty")


def signup_view(request):
    """Sign up: everyone first says whether they are a student, an alumni or faculty
    (signup.html's chooser), so nobody becomes faculty by mistake. Students and alumni go
    on to the registration page (student_views.register_view); faculty fill in the form
    here, with a password or with Google."""
    from .. import google_auth

    kind = request.POST.get("as") if request.method == "POST" else request.GET.get("as")
    kind = kind if kind in SIGNUP_KINDS else ""
    if kind in ("student", "alumni"):
        return redirect(reverse("register") + f"?as={kind}")
    if request.user.is_authenticated:
        return redirect(home_url_for(request.user))
    # Already signed in with Google (google_auth.HELD_KEY): the chooser greets them, and
    # the faculty form has their names filled in and no email or password.
    google = google_auth.held_google(request)
    ctx = {"kind": kind, "min_password_length": MIN_PASSWORD_LENGTH,
           "google_enabled": google_auth.google_enabled(), "google": google,
           "return_url": reverse("signup") + ("?as=faculty" if kind == "faculty" else "")}
    if request.method != "POST":
        if google:
            ctx["form"] = google_auth.prefill_from_google(google)
        return render(request, "signup.html", ctx)
    if not kind:
        return render(request, "signup.html", {**ctx, "error": "Please choose whether you are a student, an alumni or faculty."})

    last_name = " ".join(str(request.POST.get("last_name") or "").split())
    first_name = " ".join(str(request.POST.get("first_name") or "").split())
    middle_name = " ".join(str(request.POST.get("middle_name") or "").split())
    email = str(request.POST.get("email") or "").strip()
    password = request.POST.get("password") or ""
    password2 = request.POST.get("password2") or ""

    def failed(error):
        # everything they typed stays in the form, so only the problem needs fixing
        return render(request, "signup.html", {**ctx, "error": error, "form": request.POST})

    if not first_name or not last_name:
        return failed("Please enter your first and last name.")

    if google:
        _user, error = google_auth.create_held_account(request, "faculty", first_name, last_name,
                                                       middle_name=middle_name)
        if error:
            return render(request, "signup.html", {**ctx, "google": google_auth.held_google(request),
                                                   "error": error, "form": request.POST})
        return redirect("professor_survey")

    try:
        validate_email(email)
    except ValidationError:
        return failed("Please enter a valid email address.")

    if password != password2:
        return failed("Passwords do not match.")

    if len(password) < MIN_PASSWORD_LENGTH:
        return failed(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    if CustomUser.objects.filter(email__iexact=email).exists():
        return failed("An account with this email already exists.")

    user = CustomUser.objects.create_user(
        email=email,
        password=password,
        first_name=first_name,
        middle_name=middle_name,
        last_name=last_name,
        role=CustomUser.Role.FACULTY,  # only those who chose "faculty"; only an admin can create admins
        email_verified=True,  # faculty can use UEnvision right away, without confirming their email
        # They can use everything right away too. An administrator still approves them on the
        # Accounts page, removes them, or moves them to Student if they aren't faculty.
        is_approved=False,
    )
    notifications.notify_faculty_signup(request, user)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return redirect(home_url_for(user))


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
        messages.error(request, f"We just sent you a link. Please wait {email_verification.RESEND_WAIT_SECONDS} seconds before asking for another one.")
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
    ctx = {"sent": True, "email": email, "resend_wait": email_verification.RESEND_WAIT_SECONDS}
    if email_verification.reset_rate_limited(email):
        return render(request, "forgot_password.html", {**ctx, "wait": True})
    # Any active account with this address, whatever the capitals, including accounts made with
    # Google (no password of their own yet: the link lets them set one).
    user = CustomUser.objects.filter(email__iexact=email, is_active=True).order_by("pk").first()
    if user is None:
        log.info("Password reset asked for %s: no active account with that email", email)
    elif not email_verification.send_password_reset_email(request, user):
        # already logged with the error; don't make them wait to try again
        email_verification.release_reset_limit(email)
    # Same answer whether or not the account exists, so this can't be used to look up emails.
    return render(request, "forgot_password.html", {**ctx, "resent": request.POST.get("resend") == "1"})


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
