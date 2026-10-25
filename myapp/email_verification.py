"""Account emails: confirmation for self sign-ups (faculty signup, student/alumni
register) and the forgot-password reset link.

The link is a signed token (same mechanism as Django's password-reset links):
it expires after settings.PASSWORD_RESET_TIMEOUT and stops working once the
account is confirmed, because email_verified is part of the signed value.
"""
import logging

from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator, default_token_generator
from django.core.cache import cache
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from .models import CustomUser

log = logging.getLogger(__name__)

RESEND_WAIT_SECONDS = 60


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    key_salt = "myapp.email_verification"

    def _make_hash_value(self, user, timestamp):
        return f"{user.pk}{user.email}{user.email_verified}{timestamp}"


token_generator = EmailVerificationTokenGenerator()


def verification_required():
    return getattr(settings, "REQUIRE_EMAIL_VERIFICATION", False)


def verification_url(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    path = reverse("verify_email", args=[uid, token_generator.make_token(user)])
    return request.build_absolute_uri(path)


def send_verification_email(request, user):
    """Send the confirmation link. Returns False (and logs why) if sending failed."""
    ctx = {"user": user, "url": verification_url(request, user),
           "hours": settings.PASSWORD_RESET_TIMEOUT // 3600}
    try:
        send_mail(
            subject="Confirm your UEnvision account",
            message=render_to_string("emails/verify_email.txt", ctx),
            html_message=render_to_string("emails/verify_email.html", ctx),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
        )
    except Exception:
        log.exception("Could not send the confirmation email to %s", user.email)
        return False
    cache.set(_resend_key(user.email), True, RESEND_WAIT_SECONDS)
    return True


def can_resend(email):
    return not cache.get(_resend_key(email))


def _resend_key(email):
    return "verify-email-sent:" + email.strip().lower()


def user_from_link(uidb64, token):
    """The account a confirmation link belongs to, or None if the link is bad or expired."""
    try:
        user = CustomUser.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (CustomUser.DoesNotExist, ValueError, TypeError, OverflowError):
        return None
    return user if token_generator.check_token(user, token) else None


# ---------------------------------------------------------------------------
# Forgot password. Django's own token: it stops working as soon as the password
# changes (so a link can be used once) and after PASSWORD_RESET_TIMEOUT.
# ---------------------------------------------------------------------------
def send_password_reset_email(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    url = request.build_absolute_uri(reverse("reset_password_confirm", args=[uid, default_token_generator.make_token(user)]))
    ctx = {"user": user, "url": url, "hours": settings.PASSWORD_RESET_TIMEOUT // 3600}
    try:
        send_mail(
            subject="Reset your UEnvision password",
            message=render_to_string("emails/reset_password.txt", ctx),
            html_message=render_to_string("emails/reset_password.html", ctx),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
        )
    except Exception:
        log.exception("Could not send the password reset email to %s", user.email)
        return False
    return True


def reset_user_from_link(uidb64, token):
    try:
        user = CustomUser.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)), is_active=True)
    except (CustomUser.DoesNotExist, ValueError, TypeError, OverflowError):
        return None
    return user if default_token_generator.check_token(user, token) else None


def reset_rate_limited(email):
    """True if a reset email went to this address in the last minute (and starts the clock if not)."""
    return not cache.add("reset-email-sent:" + email.strip().lower(), True, RESEND_WAIT_SECONDS)
