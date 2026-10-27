"""Administrator notifications: an in-app list (Notifications page, with an unread
badge in the menu) and, for administrators who turn it on in Settings, an email."""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import CustomUser, Notification

log = logging.getLogger(__name__)


def _admins():
    return CustomUser.objects.filter(role__in=(CustomUser.Role.ADMINISTRATOR, CustomUser.Role.DEVELOPER), is_active=True)


def notify_faculty_signup(request, new_user):
    """A faculty member signed up and is waiting for approval: tell every administrator."""
    link = reverse("accounts") + "?status=pending"
    message = f"{new_user.get_full_name()} ({new_user.email}) signed up as faculty and is waiting for approval."
    admins = list(_admins())
    Notification.objects.bulk_create([
        Notification(recipient=a, kind=Notification.FACULTY_SIGNUP, message=message, link=link, subject_user=new_user)
        for a in admins
    ])
    to = [a.email for a in admins if a.notify_by_email]
    if not to:
        return
    ctx = {"new_user": new_user, "url": request.build_absolute_uri(link),
           "settings_url": request.build_absolute_uri(reverse("settings"))}
    try:
        send_mail(
            subject=f"UEnvision: {new_user.get_full_name()} is waiting for approval",
            message=render_to_string("emails/faculty_signup.txt", ctx),
            html_message=render_to_string("emails/faculty_signup.html", ctx),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=to,
        )
    except Exception:
        log.exception("Could not email administrators about the sign-up of %s", new_user.email)


def notify_approved(request, user):
    """Tell a faculty member their account was approved (email only)."""
    ctx = {"user": user, "url": request.build_absolute_uri(reverse("login"))}
    try:
        send_mail(
            subject="Your UEnvision account was approved",
            message=render_to_string("emails/account_approved.txt", ctx),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
        )
    except Exception:
        log.exception("Could not email %s about their approval", user.email)


def mark_read_about(user):
    """Once an account is approved, the sign-up notifications about it are done with."""
    Notification.objects.filter(subject_user=user, read_at__isnull=True).update(read_at=timezone.now())


def unread_count(user):
    if not (user.is_authenticated and user.is_administrator):
        return 0
    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()
