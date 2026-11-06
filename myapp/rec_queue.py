"""
UEnvision — runs the recommendation system automatically after surveys.

After every curriculum survey submit or edit (and when a student picks another job role),
enqueue_for_user() works out that person's recommended skills (rec_context.py) and queues
every one that has no learning resources yet (RecommendationJob). Nothing waits on Gemini
inside the request: the queue is worked through in the background,

  * by a thread started right after the submit (start_background), and
  * by `python manage.py run_automation`, which the server's timer runs every 5 minutes,
    so whatever the thread could not finish (quota, a restart) is picked up later.

Each job is one skill (+ the job role, for students) and one call to
recommendations.generate_for_skills(), which paces itself to the free tier and checks
every link. Students' resources are saved per skill AND per target job role; professors'
per skill.
"""
import threading
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections, transaction
from django.db.models import F
from django.utils import timezone

from .models import CustomUser, RecommendationJob

MAX_ATTEMPTS = 3
MAX_JOBS_PER_RUN = 30
STALE_MINUTES = 15            # a "running" job older than this was cut off (restart): run it again
PROFESSOR_SUBJECTS = 10       # subjects of one professor looked at per submit
PROFESSOR_SKILLS_PER_SUBJECT = 4

_THREAD = {"t": None}
_LOCK = threading.Lock()


def _key(skill):
    from . import gap_analysis
    hit = gap_analysis._standardize(skill)
    return hit[0] if hit else skill.strip().lower()


def enqueue(audience, skill, role="", context="", loaded=None) -> bool:
    """Queue one skill unless its resources already exist. -> True when it was queued."""
    from . import recommendations

    skill = " ".join(str(skill or "").split())[:120]
    if not skill:
        return False
    loaded = recommendations.load_all_recommendations(audience) if loaded is None else loaded
    if loaded.get((skill.lower(), role)):
        return False
    job, created = RecommendationJob.objects.get_or_create(
        audience=audience, skill_key=_key(skill)[:120], role=role,
        defaults={"skill": skill, "context": context[:300]})
    if created:
        return True
    if job.status == RecommendationJob.DONE or (job.status == RecommendationJob.FAILED and job.attempts < MAX_ATTEMPTS):
        # done but the resources are gone (file deleted) or failed earlier: try again
        RecommendationJob.objects.filter(pk=job.pk).update(status=RecommendationJob.PENDING, context=context[:300],
                                                           error="", updated_at=timezone.now())
        return True
    return job.status in (RecommendationJob.PENDING, RecommendationJob.RUNNING)


def enqueue_for_student(user) -> int:
    from . import job_roles, rec_context, recommendations
    from .student_views import MAX_TO_BUILD, TOP_SKILLS

    plan = rec_context.student_plan(user, TOP_SKILLS, MAX_TO_BUILD)
    role = user.target_role if user.target_role in job_roles.ROLE_LABELS else ""
    label = job_roles.ROLE_LABELS.get(role, "")
    loaded = recommendations.load_all_recommendations("student")
    n = 0
    for s in plan["to_build"]:
        level = s["my_level"] if s["status"] != "missing" else ""
        n += enqueue("student", s["skill"], role, rec_context.gemini_context(label, level), loaded)
    return n


def enqueue_for_professor(user) -> int:
    from . import curriculum_data, rec_context, recommendations
    from .student_views import latest_response

    latest = latest_response(user)
    if latest is None:
        return 0
    by_code = curriculum_data.subject_by_code()
    loaded = recommendations.load_all_recommendations("professor")
    n = 0
    seen = set()
    for subj in ((latest.data or {}).get("subjects") or [])[:PROFESSOR_SUBJECTS]:
        if not isinstance(subj, dict) or not subj.get("code"):
            continue
        code = str(subj["code"])
        info = by_code.get(code) or ({"name": str(subj.get("name") or code), "programs": subj.get("programs") or [],
                                      "term_label": "Added by you"} if subj.get("custom") else None)
        if not info:
            continue
        result = rec_context.faculty_subject(code, info, user, dummy=user.answers_are_dummy)
        for row in (result.get("cards") or [])[:PROFESSOR_SKILLS_PER_SUBJECT]:
            if row["key"] in seen:
                continue
            seen.add(row["key"])
            n += enqueue("professor", row["skill"], "", f"to teach within the university subject {code} — {info['name']}",
                         loaded)
    return n


def enqueue_for_user(user) -> int:
    """Queue the recommended skills of this person (student / alumni, or professor)."""
    if user.is_learner or (user.is_developer and user.learner_info):
        return enqueue_for_student(user)
    return enqueue_for_professor(user)


def after_survey(user) -> None:
    """Call after a survey submit / edit / role change: once the answers are saved (and the
    subject profiles rebuilt), queue this person's skills and start working on them."""
    if not getattr(settings, "REC_QUEUE_ENABLED", True) or not user or not user.is_authenticated:
        return

    def run():
        try:
            queued = enqueue_for_user(CustomUser.objects.get(pk=user.pk))
        except Exception as exc:   # never let this break the survey itself
            _log(f"Couldn't queue recommendations: {exc}")
            return
        if queued:
            start_background()
    transaction.on_commit(run)


# ---------------------------------------------------------------------------
# Working through the queue
# ---------------------------------------------------------------------------
def _log(text):
    try:
        from .pipeline import manager as pipeline
        pipeline.log_to_console(text, level="INFO")
    except Exception:
        pass


def _claim(skip=()):
    """The next waiting job, marked running (safe with two workers at once), or None.
    skip: job ids already tried in this run (a failed try waits for the next run)."""
    while True:
        job = (RecommendationJob.objects.filter(status=RecommendationJob.PENDING).exclude(pk__in=list(skip))
               .order_by("created_at", "pk").first())
        if job is None:
            return None
        got = RecommendationJob.objects.filter(pk=job.pk, status=RecommendationJob.PENDING).update(
            status=RecommendationJob.RUNNING, attempts=F("attempts") + 1, updated_at=timezone.now())
        if got:
            job.refresh_from_db()
            return job


def reset_stale() -> int:
    cutoff = timezone.now() - timedelta(minutes=STALE_MINUTES)
    return RecommendationJob.objects.filter(status=RecommendationJob.RUNNING, updated_at__lt=cutoff).update(
        status=RecommendationJob.PENDING)


def process(max_jobs=MAX_JOBS_PER_RUN) -> str:
    """Run up to max_jobs queued skills. Stops early when there is no API key or every key
    is out of quota (the jobs stay queued for the next run). -> a line saying what happened."""
    from . import recommendations

    reset_stale()
    done = failed = 0
    tried = set()
    for _ in range(max_jobs):
        job = _claim(tried)
        if job is None:
            break
        tried.add(job.pk)
        try:
            out = recommendations.generate_for_skills([job.skill], job.audience, job.context, job.role)
        except recommendations.RecommendationError as exc:      # e.g. no API key yet
            RecommendationJob.objects.filter(pk=job.pk).update(status=RecommendationJob.PENDING,
                                                               attempts=F("attempts") - 1, error=str(exc)[:300])
            return f"Recommendations paused: {exc}"
        except Exception as exc:
            _finish(job, ok=False, error=str(exc))
            failed += 1
            continue
        if job.skill in out["results"]:
            _finish(job, ok=True)
            done += 1
            continue
        error = out["errors"].get(job.skill) or "No resources found."
        if out["key_errors"] and "API keys failed" in error:
            # every key is out of quota: leave it queued and stop for now
            RecommendationJob.objects.filter(pk=job.pk).update(status=RecommendationJob.PENDING,
                                                               attempts=F("attempts") - 1, error=error[:300])
            return f"Recommendations paused (API quota): {done} done, {failed} failed."
        _finish(job, ok=False, error=error)
        failed += 1
    left = RecommendationJob.objects.filter(status=RecommendationJob.PENDING).count()
    return f"Recommendations: {done} done, {failed} failed, {left} waiting."


def _finish(job, ok, error=""):
    if ok:
        status = RecommendationJob.DONE
    else:
        job.refresh_from_db(fields=["attempts"])
        status = RecommendationJob.FAILED if job.attempts >= MAX_ATTEMPTS else RecommendationJob.PENDING
    RecommendationJob.objects.filter(pk=job.pk).update(status=status, error=error[:300], updated_at=timezone.now())


def start_background() -> bool:
    """Work through the queue in a background thread (one at a time per process)."""
    if not getattr(settings, "REC_QUEUE_AUTOSTART", True):
        return False
    with _LOCK:
        t = _THREAD["t"]
        if t is not None and t.is_alive():
            return False

        def run():
            try:
                _log(process())
            finally:
                close_old_connections()
        t = threading.Thread(target=run, name="uenvision-recommendations", daemon=True)
        _THREAD["t"] = t
        t.start()
    return True


def status() -> dict:
    """For Data > Recommendations."""
    counts = {s: 0 for s, _ in RecommendationJob.STATUSES}
    for s in RecommendationJob.objects.values_list("status", flat=True):
        counts[s] = counts.get(s, 0) + 1
    failed = list(RecommendationJob.objects.filter(status=RecommendationJob.FAILED).order_by("-updated_at")[:20])
    waiting = list(RecommendationJob.objects.filter(status__in=[RecommendationJob.PENDING, RecommendationJob.RUNNING])[:20])
    return {"counts": counts, "failed": failed, "waiting": waiting}


def queued_keys(audience, role=""):
    """Skill keys waiting for resources (to show "finding courses..." on the pages)."""
    return set(RecommendationJob.objects.filter(audience=audience, role=role, status__in=[
        RecommendationJob.PENDING, RecommendationJob.RUNNING]).values_list("skill_key", flat=True))
