from . import notifications


def admin_notifications(request):
    """Unread count for the Notifications badge in the menu (administrators only)."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not user.is_administrator:
        return {}
    return {"unread_notifications": notifications.unread_count(user)}
