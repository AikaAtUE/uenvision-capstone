from . import notifications


def admin_notifications(request):
    """Unread count and latest items for the notification bell (administrators only)."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not user.is_administrator:
        return {}
    from .models import Notification

    recent = list(Notification.objects.filter(recipient=user).select_related("subject_user")[:8])
    return {"unread_notifications": notifications.unread_count(user), "recent_notifications": recent}
