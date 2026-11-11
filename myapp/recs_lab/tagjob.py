"""
"Tag every skill with Gemini": a background run over all rule-tagged skills, most frequent first,
MAX_TAG_BATCH names per Gemini call, until none are left. Progress is kept in
data/.state/recs_lab_tag_job.json so the Skill categories page can show it, and a run cut off by a
restart or a used-up quota can be continued with the same button.

Names Gemini was asked about but didn't tag are remembered for the run, so they aren't sent again
and the run always ends.
"""
import threading
import time
from datetime import datetime

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from . import store, taxonomy

FILE = "tag_job"
PACE_SECONDS = 12          # 5 calls a minute (free tier)
HEARTBEAT_STALE = 120

_LOCK = threading.Lock()
_THREAD = {"t": None}


def _now():
    return timezone.now().isoformat(timespec="seconds")


def todo_names(skipped=()):
    """Rule-tagged skills from the job postings, most frequent first."""
    from . import engine

    d = engine.demand("", entry_only=False)
    if not d:
        return []
    tagger = taxonomy.Tagger()
    skipped = set(skipped)
    ranked = sorted(d["counts"].items(), key=lambda kv: (-kv[1], d["label"][kv[0]].lower()))
    return [d["label"][k] for k, _c in ranked
            if tagger(d["label"][k])["source"] == "rules" and taxonomy.key_of(d["label"][k]) not in skipped]


def state():
    s = store.load(FILE)
    beat = s.get("heartbeat")
    try:
        alive = bool(beat) and (timezone.now() - datetime.fromisoformat(beat)).total_seconds() < HEARTBEAT_STALE
    except ValueError:
        alive = False
    return {**s, "running": s.get("status") == "running" and alive}


def run(tag=None, pace=PACE_SECONDS, max_batches=1000):
    """Tag batch after batch until nothing is left. `tag` is gemini.tag_skills (swapped in tests)."""
    from . import gemini

    tag = tag or gemini.tag_skills
    s = store.load(FILE)
    skipped = set(s.get("skipped") or []) if s.get("status") in ("paused", "running") else set()
    start = todo_names(skipped)
    store.save(FILE, {"status": "running", "started_at": s.get("started_at") if skipped else _now(),
                      "heartbeat": _now(), "total": len(start) + (s.get("done", 0) if skipped else 0),
                      "done": s.get("done", 0) if skipped else 0, "batches": s.get("batches", 0) if skipped else 0,
                      "new_families": s.get("new_families", []) if skipped else [], "skipped": sorted(skipped),
                      "error": ""})
    for _ in range(max_batches):
        if store.load(FILE).get("status") != "running":     # stopped from the page
            return "stopped"
        names = todo_names(skipped)[:gemini.MAX_TAG_BATCH]
        if not names:
            store.update(FILE, lambda d: d.update(status="done", heartbeat=_now(), finished_at=_now()))
            return "done"
        try:
            res = tag(names)
        except gemini.LabGeminiError as e:
            msg = str(e)
            store.update(FILE, lambda d: d.update(status="paused", error=msg[:300], heartbeat=_now()))
            return "paused"
        tried = {taxonomy.key_of(n) for n in res.get("tried") or names}
        skipped |= tried       # tagged ones drop out of todo anyway; untagged ones must not be resent

        def fn(d, res=res):
            d.update(heartbeat=_now(), batches=d.get("batches", 0) + 1, done=d.get("done", 0) + res["tagged"],
                     skipped=sorted(skipped), new_families=d.get("new_families", []) + res.get("new_families", []))
        store.update(FILE, fn)
        if pace:
            time.sleep(pace)
    store.update(FILE, lambda d: d.update(status="paused", error="Stopped after too many batches.", heartbeat=_now()))
    return "paused"


def start():
    if not getattr(settings, "RECS_LAB_WORKER_AUTOSTART", True) or state()["running"]:
        return False
    with _LOCK:
        t = _THREAD["t"]
        if t is not None and t.is_alive():
            return False

        def go():
            try:
                run()
            except Exception as e:  # noqa: BLE001  never leave it showing "running"
                msg = f"{type(e).__name__}: {e}"
                store.update(FILE, lambda d: d.update(status="paused", error=msg[:300]))
            finally:
                close_old_connections()
        t = threading.Thread(target=go, name="recs-lab-tagging", daemon=True)
        _THREAD["t"] = t
        t.start()
    return True


def stop():
    store.update(FILE, lambda d: d.update(status="paused", error="Stopped by a developer."))
