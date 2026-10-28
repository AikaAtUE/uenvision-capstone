"""Limits on failed logins (login page and /admin/ login, which goes through it).

* Per account: MAX_PER_EMAIL wrong passwords for one email within WINDOW_SECONDS pause
  logins for that email for WINDOW_SECONDS. A successful login (or a password reset
  from the emailed link) clears it.
* Per computer: MAX_PER_IP failed logins from one IP address within WINDOW_SECONDS,
  whatever the emails, pause logins from that address for WINDOW_SECONDS.

It works the same whether or not the email has an account, so the message can't be used
to look up who is registered. Counts live in the cache, which is the database
(settings.CACHES), so all gunicorn workers share them.
"""
import hashlib
import math
import time

from django.core.cache import cache

MAX_PER_EMAIL = 5
MAX_PER_IP = 20
WINDOW_SECONDS = 15 * 60


def client_ip(request):
    """nginx puts the visitor's address in X-Real-IP (deploy/nginx-uenvision.conf);
    without nginx (runserver) REMOTE_ADDR is the visitor."""
    return (request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR") or "unknown").strip()


def _keys(request, email):
    digest = hashlib.sha256(str(email or "").strip().lower().encode()).hexdigest()
    return [(f"login-fail:email:{digest}", MAX_PER_EMAIL), (f"login-fail:ip:{client_ip(request)}", MAX_PER_IP)]


def blocked_for(request, email):
    """Seconds until this email / this computer may try again, or 0 if it may try now."""
    now = time.time()
    waits = [cache.get("lock:" + key, 0) - now for key, _ in _keys(request, email)]
    return max(0, math.ceil(max(waits)))


def record_failure(request, email):
    for key, limit in _keys(request, email):
        cache.add(key, 0, WINDOW_SECONDS)   # starts the window on the first failure
        try:
            count = cache.incr(key)
        except ValueError:                  # expired between add() and incr()
            cache.set(key, 1, WINDOW_SECONDS)
            count = 1
        if count >= limit:
            cache.set("lock:" + key, time.time() + WINDOW_SECONDS, WINDOW_SECONDS)
            cache.delete(key)


def clear_email(email):
    """A successful login or password reset: that account starts over. (The IP count stays,
    so one good login can't be used to keep guessing other accounts.)"""
    digest = hashlib.sha256(str(email or "").strip().lower().encode()).hexdigest()
    cache.delete_many([f"login-fail:email:{digest}", f"lock:login-fail:email:{digest}"])


def message(seconds):
    minutes = max(1, math.ceil(seconds / 60))
    return (f"Too many login attempts. Try again in {minutes} minute{'' if minutes == 1 else 's'}, "
            "or use Forgot password.")
