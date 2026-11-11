"""
The new recommendation system on the real site pages.

The Recommendations page and the students' / alumni's "Recommended for you" use the lab's engine:
blueprints, skill families, statuses and learning resources.

The original system is untouched and keeps running in the background: its views, templates, Gemini
queue and saved resources stay as they were, and developers (only) can open it at
/recommendations/classic/. There is no switch on the site; settings.RECS_SYSTEM = "classic" brings the
original pages back everywhere (the test suite uses it for the original system's tests).
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from ..models import CurriculumSurveyResponse, CustomUser
from ..views.common import _sees_dummy_results, _sees_student_view
from . import blueprints, engine, resources, taxonomy, worker

CLASSIC_FLAG = "recs_classic"   # set on the request by classic_view, so the learner page renders as before


def is_new(request=None):
    from django.conf import settings
    if request is not None and getattr(request, CLASSIC_FLAG, False):
        return False
    return getattr(settings, "RECS_SYSTEM", "new") != "classic"


def _resource_context(request, specs, auto=True):
    """Queues what's missing (in the background, deduplicated, so opening a page never waits on
    Gemini) and returns the resource bar's context."""
    keys = {s["key"] for s in specs}
    have = resources.saved()
    missing = [s for s in specs if s["key"] not in have]
    from django.conf import settings
    auto = auto and getattr(settings, "RECS_LAB_WORKER_AUTOSTART", True)
    if auto and missing and worker.enqueue(missing):
        worker.start()
    st = worker.status(keys)
    return {"res_missing": sum(1 for k in keys if k not in have), "res_total": len(keys), "res_status": st,
            "free_only": request.GET.get("free") == "1", "res_live": True}


# ---------------------------------------------------------------------------
# Recommendations page (faculty, administrators, developers)
# ---------------------------------------------------------------------------
@login_required
def recommendations_view(request):
    from ..views import dashboard as classic

    if not is_new(request) or _sees_student_view(request):
        return classic.recommendations_view(request)   # developers' Student / Alumni view: the learner page
    user = request.user
    dummy = _sees_dummy_results(request)
    is_admin = user.is_administrator
    subs = blueprints.subjects()
    taught = {c for r in engine.responses(dummy) if r["type"] == CurriculumSurveyResponse.PROFESSOR
              and r["user_id"] == user.pk for c in r["subjects"]}
    mine = [s for s in subs if s["code"] in taught]
    codes = {s["code"] for s in subs}

    code = request.GET.get("subject") if request.GET.get("subject") in codes else ""
    # Administrators get three tabs: Curriculum gaps (their start page), Faculty view (any subject) and Subject
    # blueprints. Faculty only get the faculty view of their subjects.
    views = ("gaps", "subject", "blueprints") if is_admin else ("subject",)
    view = request.GET.get("view") if request.GET.get("view") in views else ("subject" if code else views[0])
    if view == "subject" and not code:
        code = (mine or subs)[0]["code"] if (mine or subs) else ""

    base = reverse("recommendations")
    ctx = {"active_page": "recommendations", "subjects": subs, "mine": mine, "is_admin": is_admin,
           "view": view, "code": code, "lab_pages": set(), "subject_url": base,
           "bp_url": f"{base}?view=blueprints&" if is_admin else "", "faculty_url": f"{base}?view=subject&"}
    if view == "blueprints":
        from .views import blueprint_action, blueprint_context
        bp_code = request.GET.get("subject") or request.POST.get("subject") or ""
        if request.method == "POST":
            blueprint_action(request, bp_code, dummy)
            return redirect(f"{base}?view=blueprints&subject={bp_code}")
        ctx.update(blueprint_context(bp_code))
        return render(request, "recs_lab/live_recommendations.html", ctx)
    if view == "gaps":
        program = request.GET.get("program") if request.GET.get("program") in ("BSIT", "BSCS") else ""
        levels = "all" if request.GET.get("levels") == "all" else "entry"
        try:
            floor = max(0.5, min(25.0, float(request.GET.get("floor") or engine.DEFAULT_FLOOR)))
        except ValueError:
            floor = engine.DEFAULT_FLOOR
        kind = request.GET.get("kind") if request.GET.get("kind") in taxonomy.KINDS else ""
        result = engine.admin_gaps(program, entry_only=levels == "entry", floor=floor, dummy=dummy, limit=1000)
        rows = [r for r in result["all_rows"] if not kind or r["kind"] == kind][:10] if result.get("exists") else []
        specs = resources.plan_admin(rows)
        ctx.update(result=result, rows=rows, program=program, levels=levels, floor=floor, kind=kind,
                   kinds=taxonomy.KINDS, view_param="view=gaps&", form_action=reverse("recommendations"))
    else:
        prof = user.pk if code in taught else None
        result = engine.faculty_view(code, professor_id=prof, dummy=dummy) if code else {"exists": False}
        specs = resources.plan_faculty(result) if result.get("exists") else []
        ctx.update(result=result, prof=prof, teaches=code in taught)
    if request.method == "POST" and request.POST.get("action") == "find_resources":
        n = worker.enqueue(specs)
        worker.start()
        messages.info(request, f"Looking for resources for {n} more item{'s' if n != 1 else ''}." if n
                      else "Already looking for this page's resources.")
        return redirect(request.get_full_path())
    ctx.update(_resource_context(request, specs))
    return render(request, "recs_lab/live_recommendations.html", ctx)


# ---------------------------------------------------------------------------
# Students and alumni ("Recommended for you" on their skill gap page)
# ---------------------------------------------------------------------------
def learner_context(request, user, is_alumni):
    """Extra context for student_dashboard.html when the new system is on: {"new_recs": ...}.
    Empty when the classic system is on, so the page renders exactly as before."""
    if not is_new(request):
        return {}
    dummy = _sees_dummy_results(request)
    result = engine.alumni_view(user, dummy) if is_alumni else engine.student_view(user, dummy)
    if not result.get("exists"):
        return {"new_recs": {"exists": False}}
    free_only = request.GET.get("free") == "1"
    specs = (resources.plan_alumni if is_alumni else resources.plan_student)(result, free_only)
    return {"new_recs": result, "new_recs_alumni": is_alumni, "res_find_url": reverse("recs_live_find"),
            "res_anchor": "#recommended", **_resource_context(request, specs)}


@login_required
def classic_view(request):
    """The original Recommendations page, still running in the background. Developers only; everyone else
    gets a 404, as if it weren't there. With the developer Student / Alumni view on, it shows the original
    learner recommendations."""
    from django.http import Http404
    from ..views import dashboard as classic

    if not request.user.is_developer:
        raise Http404
    setattr(request, CLASSIC_FLAG, True)
    return classic.recommendations_view(request)


@login_required
@require_POST
def find_view(request):
    """The learner page's "Find resources" button: queue what's missing for this account."""
    from ..context_processors import dev_learner_view

    as_kind = dev_learner_view(request) if request.user.is_developer else None
    is_alumni = as_kind == "alumni" if as_kind else request.user.role == CustomUser.Role.ALUMNI
    dummy = _sees_dummy_results(request)
    result = engine.alumni_view(request.user, dummy) if is_alumni else engine.student_view(request.user, dummy)
    if result.get("exists"):
        specs = (resources.plan_alumni if is_alumni else resources.plan_student)(result)
        worker.enqueue(specs)
        worker.start()
    messages.info(request, "Looking for learning resources in the background. They appear here within a few minutes.")
    nxt = request.POST.get("next") or ""
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect("student_dashboard")
