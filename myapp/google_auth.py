"""Google sign-in (django-allauth).

* Anyone whose Google email already has a UEnvision account (any role) is logged in
  to that account: "Continue with Google" on the login page. Their password keeps
  working too.
* A Google account with no UEnvision account yet is not made into one straight away.
  pre_social_login() keeps it in the session (HELD_KEY) and sends them back to the page
  they came from: the sign-up chooser ("Who are you?") when they came from the login
  page, or the registration / faculty form when they pressed Continue with Google there
  (start_google_signup_view, which also keeps what they had typed). Those pages then
  show "Signed in using <email> through Google", fill in the names from Google, and
  hide the email and password fields. The account is only created when they press
  "Create account and start the survey" (create_held_account).

The keys come from GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET in .env (settings.py).
Without them google_enabled() is False and the Google buttons are hidden.
"""
from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.adapter import get_adapter as get_social_adapter

# Session keys. PENDING_KEY: {"return_to", "form"} while they are at Google's account
# chooser, from a sign-up form. HELD_KEY: the Google account that came back with no
# UEnvision account yet: {"sociallogin", "email", "first_name", "last_name", "form"}.
PENDING_KEY = "google_pending_registration"
HELD_KEY = "google_held_signup"
UE_EMAIL_DOMAIN = "ue.edu.ph"
# Fields of a sign-up form that are never kept in the session.
_NOT_KEPT = ("csrfmiddlewaretoken", "password", "password2", "method", "next")


def google_enabled():
    return bool(getattr(settings, "GOOGLE_CLIENT_ID", "") and getattr(settings, "GOOGLE_CLIENT_SECRET", ""))


def is_ue_email(email):
    domain = str(email or "").rsplit("@", 1)[-1].lower()
    return "@" in str(email or "") and (domain == UE_EMAIL_DOMAIN or domain.endswith("." + UE_EMAIL_DOMAIN))


def start_google_login(request, next_url=""):
    """Send the browser to Google's account chooser (used by the registration page)."""
    provider = get_social_adapter(request).get_provider(request, "google")
    return provider.redirect(request, "login", next_url=next_url or None)


def held_google(request):
    """The Google account waiting to become a UEnvision account, for the sign-up pages:
    {"email", "first_name", "last_name", "form"}, or None."""
    held = request.session.get(HELD_KEY)
    if not held or not google_enabled():
        return None
    return {"email": held.get("email") or "", "first_name": held.get("first_name") or "",
            "last_name": held.get("last_name") or "", "form": held.get("form") or {}}


def prefill_from_google(google):
    """Form values for a sign-up page: what they had typed before going to Google, with
    the names from Google where they had not typed one."""
    form = dict(google.get("form") or {})
    for k in ("first_name", "last_name"):
        if not form.get(k):
            form[k] = google.get(k) or ""
    return form


def start_google_signup_view(request):
    """Continue with Google (or Use a different account) on a sign-up page: keep what
    they typed, then send them to Google's account chooser. They come back to `next`."""
    from django.utils.http import url_has_allowed_host_and_scheme
    if request.method != "POST" or not google_enabled():
        return redirect("signup")
    next_url = request.POST.get("next") or ""
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()},
                                           require_https=request.is_secure()):
        next_url = reverse("signup")
    request.session.pop(HELD_KEY, None)
    request.session[PENDING_KEY] = {
        "return_to": next_url,
        "form": {k: v for k, v in request.POST.items() if k not in _NOT_KEPT and v},
    }
    return start_google_login(request)


def create_held_account(request, role, first_name, last_name, middle_name="", info=None, target_role=""):
    """Makes the UEnvision account for the Google account in the session and logs them
    in. Returns (user, error)."""
    from django.contrib.auth import login
    from allauth.socialaccount.models import SocialLogin
    from .models import CustomUser

    held = request.session.get(HELD_KEY)
    if not held:
        return None, "Your Google sign-in has expired. Please press Continue with Google again."
    sociallogin = SocialLogin.deserialize(held["sociallogin"])
    user = sociallogin.user
    if CustomUser.objects.filter(email__iexact=user.email).exists():
        request.session.pop(HELD_KEY, None)
        return None, f"An account with {user.email} already exists. Please log in instead."
    faculty = role == "faculty"
    user.role = {"faculty": CustomUser.Role.FACULTY,
                 "alumni": CustomUser.Role.ALUMNI}.get(role, CustomUser.Role.STUDENT)
    user.first_name, user.middle_name, user.last_name = first_name, middle_name or "", last_name
    if faculty:
        user.is_approved = False   # like a faculty password sign-up: an administrator checks them
    else:
        user.learner_info = info or {}
        user.target_role = target_role or ""
    user.email_verified = True     # Google confirmed it
    user.set_unusable_password()   # they can set one later with Forgot password
    sociallogin.save(request)
    request.session.pop(HELD_KEY, None)
    login(request, user, backend="allauth.account.auth_backends.AuthenticationBackend")
    if faculty:
        from . import notifications
        notifications.notify_faculty_signup(request, user)
    return user, None


class AccountAdapter(DefaultAccountAdapter):
    """allauth's own email/password sign-up pages are never used: /signup/ asks who they
    are, then students and alumni register on /register/ and faculty on /signup/?as=faculty."""

    def is_open_for_signup(self, request):
        return False

    def get_login_redirect_url(self, request):
        from .views.common import home_url_for
        return home_url_for(request.user)


class SocialAccountAdapter(DefaultSocialAccountAdapter):

    def is_open_for_signup(self, request, sociallogin):
        return False   # new accounts are made by create_held_account(), never by allauth itself

    def pre_social_login(self, request, sociallogin):
        user = sociallogin.user
        if user is not None and user.pk:
            # An existing account with this Google email. allauth would wipe its password
            # unless the email counts as confirmed; keep the password for accounts whose
            # email UEnvision already treats as confirmed.
            from allauth.account.models import EmailAddress
            if user.email_verified:
                EmailAddress.objects.update_or_create(
                    user=user, email__iexact=user.email,
                    defaults={"email": user.email, "verified": True, "primary": True})
            else:
                user.email_verified = True   # they just proved they own it
                user.save(update_fields=["email_verified"])
            request.session.pop(PENDING_KEY, None)
            request.session.pop(HELD_KEY, None)
            return
        if sociallogin.is_existing:
            return
        # No UEnvision account yet: keep the Google account until they finish signing up.
        pending = request.session.pop(PENDING_KEY, None) or {}
        request.session[HELD_KEY] = {
            "sociallogin": sociallogin.serialize(),
            "email": (user.email or "").strip(),
            "first_name": " ".join((user.first_name or "").split()),
            "last_name": " ".join((user.last_name or "").split()),
            "form": pending.get("form") or {},
        }
        raise ImmediateHttpResponse(redirect(pending.get("return_to") or reverse("signup")))

    def get_connect_redirect_url(self, request, socialaccount):
        return reverse("settings")
