"""Google sign-in (django-allauth).

* Anyone whose Google email already has a UEnvision account (any role) is logged in
  to that account: "Continue with Google" on the login page. Their password keeps
  working too.
* A new student / alumni can register with Google from the registration page
  (students with their UE Google account; alumni with any Google account, since they
  may no longer have their UE one)
  (student_views.register_view). That page checks their personal information first,
  keeps it in the session (PENDING_KEY), then sends them to Google; when Google sends
  them back, SocialAccountAdapter.save_user() makes the account from it.
* A Google account with no UEnvision account, that did not come from the
  registration page, is not signed up: they are sent back to the login page with a
  note on how to register.

The keys come from GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET in .env (settings.py).
Without them google_enabled() is False and the Google buttons are hidden.
"""
from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.adapter import get_adapter as get_social_adapter

# Session key: {"role", "name", "info", "target_role"} from the registration page,
# waiting for Google to confirm the email.
PENDING_KEY = "google_pending_registration"
UE_EMAIL_DOMAIN = "ue.edu.ph"


def google_enabled():
    return bool(getattr(settings, "GOOGLE_CLIENT_ID", "") and getattr(settings, "GOOGLE_CLIENT_SECRET", ""))


def is_ue_email(email):
    domain = str(email or "").rsplit("@", 1)[-1].lower()
    return "@" in str(email or "") and (domain == UE_EMAIL_DOMAIN or domain.endswith("." + UE_EMAIL_DOMAIN))


def start_google_login(request, next_url=""):
    """Send the browser to Google's account chooser (used by the registration page)."""
    provider = get_social_adapter(request).get_provider(request, "google")
    return provider.redirect(request, "login", next_url=next_url or None)


def _back_to_login(request, text):
    messages.error(request, text)
    return ImmediateHttpResponse(redirect("login"))


class AccountAdapter(DefaultAccountAdapter):
    """allauth's own email/password sign-up pages are never used: students and alumni
    register on /register/ and faculty on /signup/."""

    def is_open_for_signup(self, request):
        return False

    def get_login_redirect_url(self, request):
        from .views.common import home_url_for
        return home_url_for(request.user)


class SocialAccountAdapter(DefaultSocialAccountAdapter):

    def is_open_for_signup(self, request, sociallogin):
        return bool(request.session.get(PENDING_KEY))

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
            elif not user.email_verified:
                user.email_verified = True   # they just proved they own it
                user.save(update_fields=["email_verified"])
            request.session.pop(PENDING_KEY, None)
            return
        if sociallogin.is_existing:
            return
        email = (sociallogin.user.email or "").strip() if sociallogin.user else ""
        pending = request.session.get(PENDING_KEY)
        if not pending:
            raise _back_to_login(
                request,
                f"There is no UEnvision account for {email or 'that Google account'} yet. "
                "Students and fresh graduates: press Check your skill gap to register first. "
                "Faculty: sign up first, then you can use Continue with Google.")
        if pending.get("role") != "alumni" and not is_ue_email(email):
            messages.error(request, f"Please choose your UE Google account (ending in @{UE_EMAIL_DOMAIN}). "
                                    f"{email or 'That account'} is not a UE email.")
            raise ImmediateHttpResponse(redirect(reverse("register") + f"?as={pending.get('role', 'student')}"))

    def save_user(self, request, sociallogin, form=None):
        from .models import CustomUser

        pending = request.session.pop(PENDING_KEY, None) or {}
        user = sociallogin.user
        user.role = (CustomUser.Role.ALUMNI if pending.get("role") == "alumni" else CustomUser.Role.STUDENT)
        user.first_name = pending.get("first_name") or user.first_name or user.email.split("@")[0]
        user.last_name = pending.get("last_name") or user.last_name or ""
        user.learner_info = pending.get("info") or {}
        user.target_role = pending.get("target_role") or ""
        user.email_verified = True
        user.set_unusable_password()   # they can set one later with Forgot password
        return super().save_user(request, sociallogin, form)

    def get_connect_redirect_url(self, request, socialaccount):
        return reverse("settings")
