"""
Background finder for the lab's learning resources. A page's "Find resources" button queues the
requests that have nothing saved yet (data/.state/recs_lab_resource_queue.json) and starts one thread
that works through them, paced to the free tier. Nothing waits on Gemini inside a request.

One worker at a time across gunicorn workers: the thread writes a heartbeat, and another process only
starts its own when the heartbeat is older than HEARTBEAT_STALE seconds.
"""
import threading
import time
from datetime import datetime, timedelta

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from . import resources, store

FILE = "resource_queue"
PACE_SECONDS = 12            # 5 requests a minute, the free tier's limit
MAX_ATTEMPTS = 3
HEARTBEAT_STALE = 90
RUNNING_STALE = timedelta(minutes=10)

_LOCK = threading.Lock()
_THREAD = {"t": None}


def _now():
    return timezone.now()


def _parse(stamp):
    try:
        return datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None


def jobs():
    return store.load(FILE).get("jobs") or {}


def enqueue(specs):
    """Queue requests with nothing saved (and not already queued). -> how many were added."""
    have = resources.saved()
    added = []

    def fn(data):
        q = data.setdefault("jobs", {})
        for sp in specs:
            k = sp["key"]
            if k in have or (k in q and q[k].get("status") != "failed"):
                continue
            q[k] = {**sp, "status": "pending", "attempts": 0, "error": "",
                    "queued_at": _now().isoformat(timespec="seconds")}
            added.append(k)
    store.update(FILE, fn)
    return len(added)


def requeue(sp):
    """Find this one again even if something is saved (the Refresh button)."""
    def fn(data):
        data.setdefault("jobs", {})[sp["key"]] = {**sp, "status": "pending", "attempts": 0, "error": "",
                                                  "queued_at": _now().isoformat(timespec="seconds")}
    store.update(FILE, fn)


def drop(k):
    store.update(FILE, lambda data: data.setdefault("jobs", {}).pop(k, None))


def status(keys=None):
    """{"pending": n, "failed": n, "running": bool} for the given keys (all when None)."""
    q = jobs()
    sel = [j for k, j in q.items() if keys is None or k in keys]
    beat = _parse((store.load(FILE).get("worker") or {}).get("heartbeat"))
    return {"pending": sum(1 for j in sel if j["status"] in ("pending", "running")),
            "failed": sum(1 for j in sel if j["status"] == "failed"),
            "running": bool(beat and (_now() - beat).total_seconds() < HEARTBEAT_STALE)}


def _claim():
    """Mark the oldest pending job running. -> its spec, or None."""
    picked = {}

    def fn(data):
        q = data.setdefault("jobs", {})
        for j in q.values():   # a job left "running" by a restart goes back to pending
            started = _parse(j.get("started_at"))
            if j["status"] == "running" and (not started or _now() - started > RUNNING_STALE):
                j["status"] = "pending"
        pending = sorted((j for j in q.values() if j["status"] == "pending"), key=lambda j: j.get("queued_at", ""))
        if pending:
            j = pending[0]
            j.update(status="running", started_at=_now().isoformat(timespec="seconds"),
                     attempts=j.get("attempts", 0) + 1)
            picked.update(j)
        data["worker"] = {"heartbeat": _now().isoformat(timespec="seconds")}
    store.update(FILE, fn)
    return picked or None


def _finish(k, error=""):
    def fn(data):
        q = data.setdefault("jobs", {})
        if not error:
            q.pop(k, None)
        elif k in q:
            q[k].update(status="failed" if q[k].get("attempts", 0) >= MAX_ATTEMPTS else "pending", error=error[:300])
    store.update(FILE, fn)


def process(max_jobs=40, ask=None, pace=PACE_SECONDS):
    """Work through the queue. -> a line saying what happened."""
    from .gemini import LabGeminiError

    done = failed = 0
    last = 0.0
    for _ in range(max_jobs):
        job = _claim()
        if not job:
            break
        wait = pace - (time.time() - last)
        if wait > 0 and last:
            time.sleep(wait)
        last = time.time()
        try:
            items = resources.find(job, ask=ask)
        except resources.NothingFound as e:
            if job.get("attempts", 0) >= MAX_ATTEMPTS:
                resources.save_entry(job, [], error=str(e))   # saved as "nothing found" so it isn't retried
                _finish(job["key"])
            else:
                _finish(job["key"], str(e))
            failed += 1
            continue
        except LabGeminiError as e:
            # no key / every key out of quota: leave it queued and stop for now
            def fn(data, k=job["key"], msg=str(e)):
                j = data.setdefault("jobs", {}).get(k)
                if j:
                    j.update(status="pending", attempts=max(0, j.get("attempts", 1) - 1), error=msg[:300])
            store.update(FILE, fn)
            return f"Paused: {e}"
        except Exception as e:  # noqa: BLE001  (network trouble while checking links, etc.)
            _finish(job["key"], f"{type(e).__name__}: {e}")
            failed += 1
            continue
        resources.save_entry(job, items)
        _finish(job["key"])
        done += 1
    return f"{done} found, {failed} failed."


def start():
    """Start the background thread unless one is already running here or in another process."""
    if not getattr(settings, "RECS_LAB_WORKER_AUTOSTART", True):
        return False
    if status()["running"]:
        return False
    with _LOCK:
        t = _THREAD["t"]
        if t is not None and t.is_alive():
            return False

        def run():
            try:
                process()
            finally:
                close_old_connections()
                store.update(FILE, lambda data: data.pop("worker", None))
        t = threading.Thread(target=run, name="recs-lab-resources", daemon=True)
        _THREAD["t"] = t
        t.start()
    return True
