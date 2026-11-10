

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from ..pipeline import manager as pipeline
from .. import curriculum_data
from .. import feedback_nudge
from .. import gap_analysis
from .. import ghost_jobs
from .. import job_roles
from .. import rec_context
from .. import rec_queue
from .. import recommendations
from .common import _sees_dummy_results, _sees_student_view, administrator_required


@login_required
def dashboard_view(request):
    from ..student_views import latest_response

    if _sees_student_view(request):
        from ..context_processors import dev_learner_view
        from ..student_views import render_student_dashboard
        return render_student_dashboard(request, active_page="dashboard", as_kind=dev_learner_view(request))
    feedback_nudge.record_use(request.user)
    return render(request, "dashboard.html", {"active_page": "dashboard",
                                              "has_professor_record": latest_response(request.user) is not None,
                                              "exclude_ghost_jobs": bool(request.session.get(ghost_jobs.SESSION_KEY))})


@login_required
def dashboard_skills_view(request):
    """JSON for the dashboard's top-skills bar chart, skills-per-month line chart,
    and (added alongside the existing two) the skill gap analysis against the
    curriculum surveys — see gap_analysis.py for exactly what that compares."""
    try:
        top = int(request.GET.get("top", 10))
        months = int(request.GET.get("months", 0))
    except ValueError:
        return JsonResponse({"ok": False, "error": "Bad number."}, status=400)
    if not 1 <= top <= 30 or not 0 <= months <= 600:
        return JsonResponse({"ok": False, "error": "Top must be 1-30."}, status=400)
    pipeline.ensure_skill_csvs()
    ghost = request.GET.get("ghost", "")
    if ghost in ("exclude", "include"):
        # The "Exclude possible ghost jobs" switch: remembered for this login, and applied
        # right away to this response (GhostJobsMiddleware applies it on later pages).
        request.session[ghost_jobs.SESSION_KEY] = ghost == "exclude"
        ghost_jobs.EXCLUDE.set(ghost == "exclude")
    # The ticked job sources, comma-separated ("" = all of them). Only the scraped job boards
    # can be picked: imported datasets such as Djinni never count on the Dashboard.
    picked = [s for s in request.GET.get("source", "").lower().split(",") if s.strip()]
    if any(s not in pipeline.SOURCES for s in picked):
        return JsonResponse({"ok": False, "error": "Unknown source."}, status=400)
    source = picked if picked and set(picked) != set(pipeline.SOURCES) else ""
    level = request.GET.get("level", "")
    program = request.GET.get("program", "")
    if program and program not in curriculum_data.PROGRAMS:
        return JsonResponse({"ok": False, "error": "Unknown program."}, status=400)
    try:
        data = pipeline.skills_dashboard(request.GET.get("kind", "hard"), top, source, level, months, program)
    except (OSError, UnicodeDecodeError) as exc:
        return JsonResponse({"ok": False, "error": f"Couldn't read the data: {exc}"}, status=500)
    if data.get("exists"):
        data["ghost"] = job_roles.ghost_summary(source, level, program)
        try:
            data["gap"] = gap_analysis.compute(top, source, level, program, dummy=_sees_dummy_results(request))
        except (OSError, UnicodeDecodeError) as exc:
            data["gap"] = {"exists": False, "error": str(exc)}
        _scope_gap_for(request.user, data["gap"])
        data["training"] = _training_overview(data)
    return JsonResponse({"ok": True, **data})


TRAINING_OVERVIEW_SIZE = 5


def _training_overview(data):
    """Up to 5 training resources for the Dashboard's "Recommended training" card: one per
    skill, for the most under-taught skills (Skill gap analysis), or, before there are
    survey answers, the most in-demand skills in the bar chart. Only resources already
    generated on the Recommendations page are used, so this never calls Gemini."""
    cached = recommendations.load_recommendations()
    if not cached:
        return {"basis": "", "items": []}
    gap = data.get("gap") or {}
    under = [r["skill"] for r in gap.get("under_taught") or []] if gap.get("has_survey_data") else []
    basis, skills = ("under_taught", under) if under else ("in_demand", [b["skill"] for b in data.get("bars") or []])
    items = []
    for skill in skills:
        rows = [x for x in cached.get(skill.strip().lower()) or []
                if (x.get("link") or "").startswith(("https://", "http://"))]
        if not rows:
            continue
        r = next((x for x in rows if x.get("verified") == "link checked"), rows[0])
        items.append({"skill": skill, "name": r.get("name") or "", "link": r.get("link") or "",
                      "type": r.get("type") or "", "provider": r.get("provider") or ""})
        if len(items) == TRAINING_OVERVIEW_SIZE:
            break
    return {"basis": basis if items else "", "items": items}


def _scope_gap_for(user, gap):
    """Administrators see the whole report, including where job postings, faculty and
    students don't match. Faculty see the subjects they teach (their syllabus side):
    the By subject table only lists their own subjects, and the three-source comparison
    is left out."""
    if user.is_administrator or not gap.get("exists"):
        gap["scope"] = "all"
        return
    mine = {code for code, _ in _my_subjects(user)}
    gap.pop("comparison", None)
    gap["by_subject"] = [r for r in gap.get("by_subject") or [] if r["code"] in mine]
    gap["scope"] = "mine"


MAX_CURRICULUM_SUGGESTIONS = 12


def _curriculum_suggestions(user, gap, subject_value=""):
    """Subjects where in-demand skills that fit the subject (per the MIND ontology) are not
    reported as taught there by anyone yet: a suggestion for the curriculum. Faculty get
    their own subjects; administrators get every subject. With a subject chosen, only that one."""
    if not gap.get("exists"):
        return []
    scoped = dict(gap)
    _scope_gap_for(user, scoped)
    # Practicum / research / capstone and the placeholder Professional Electives aren't
    # subjects a professor picks on this page (_subject_choices), so they aren't suggested either.
    rows = [r for r in scoped.get("by_subject") or []
            if r["could_add"] and r["code"] not in curriculum_data.HIDDEN_FROM_PROFESSORS]
    if subject_value:
        rows = [r for r in rows if r["code"] == subject_value]
    return rows[:MAX_CURRICULUM_SUGGESTIONS]


def _subject_choices():
    """[(code, label)] for every subject professors teach, once per code (subjects
    that BSIT and BSCS share are listed once; practicum/research/capstone and the
    placeholder Professional Electives are left out)."""
    tags = curriculum_data.subject_term_tags()
    subjects = sorted(curriculum_data.subject_by_code().items(),
                      key=lambda item: curriculum_data.subject_sort_key(item[0], tags))
    return [(code, f"{code} — {info['name']}") for code, info in subjects
            if code not in curriculum_data.HIDDEN_FROM_PROFESSORS]


def _subject_code(value):
    """Subject code from a ?subject= value; also accepts the older "PROGRAM|CODE" form."""
    return str(value or "").split("|")[-1]


def _my_custom_subjects(user):
    """{code: {"name", "programs", "term_label"}} for the subjects this professor added
    themselves because they aren't in the curriculum list (e.g. an elective)."""
    from ..student_views import latest_response

    latest = latest_response(user)
    out = {}
    for subj in ((latest.data or {}).get("subjects") or []) if latest else []:
        if isinstance(subj, dict) and subj.get("custom") and subj.get("code"):
            out[str(subj["code"])] = {"name": str(subj.get("name") or ""), "programs": subj.get("programs") or [],
                                      "term_label": "Added by you"}
    return out


def _my_subjects(user):
    """Subjects in this professor's current record (latest Professor Survey response,
    possibly edited on Data -> My subjects & skills), including ones they added."""
    from ..student_views import latest_response

    seen, out = set(), []
    labels = dict(_subject_choices())
    labels.update({code: f"{code} — {info['name']}" for code, info in _my_custom_subjects(user).items()})
    latest = latest_response(user)
    for data in ([latest.data] if latest else []):
        for subj in (data or {}).get("subjects") or []:
            value = str(subj.get("code") or "")
            if value in labels and value not in seen:
                seen.add(value)
                out.append((value, labels[value]))
    return out


@login_required
def recommendations_view(request):
    """Professor recommendations. Two views of the same page:
    * no subject chosen: the ranked under-taught-skills list (reusing
      gap_analysis.py — same list the Dashboard's Skill Gap Analysis tab shows);
    * ?subject=CODE: in-demand skills that fit that subject, ranked by
      demand minus how deeply the Professor Survey says they're already taught
      there (gap_analysis.subject_targets).
    Either way, already generated Gemini resources are shown. Generating more is a
    separate POST (recommendations_generate_view) so simply opening this page never
    spends API quota."""
    if _sees_student_view(request):
        from ..context_processors import dev_learner_view
        from ..student_views import render_student_dashboard
        return render_student_dashboard(request, active_page="recommendations", as_kind=dev_learner_view(request))
    feedback_nudge.record_use(request.user)
    cached = recommendations.load_recommendations()
    subject_value = _subject_code(request.GET.get("subject", ""))
    choices = _subject_choices()
    custom = _my_custom_subjects(request.user)
    subject = None
    dummy = _sees_dummy_results(request)
    gap = gap_analysis.compute(top=10, dummy=dummy)
    faculty = None
    if subject_value in dict(choices) or subject_value in custom:
        # context-aware: taught by you / learned by students / earlier year levels / demand
        faculty = rec_context.faculty_subject(subject_value, info=custom.get(subject_value), user=request.user,
                                              dummy=dummy)
        subject = faculty
        rows = list(faculty.get("rows") or []) if faculty.get("exists") else []
    else:
        subject_value = ""
        rows = list(gap.get("under_taught") or []) if gap.get("exists") else []
    waiting = rec_queue.queued_keys("professor")
    for row in rows:
        row["cached_resources"] = cached.get(row["skill"].strip().lower(), [])
        row["finding"] = not row["cached_resources"] and row.get("key") in waiting
    return render(request, "recommendations.html", {
        "curriculum_suggestions": _curriculum_suggestions(request.user, gap, subject_value),
        "ghost": job_roles.ghost_summary(),
        "active_page": "recommendations",
        "gap": gap,
        "under_taught": rows,
        "subject": subject,
        "faculty": faculty,
        "subject_value": subject_value,
        "subject_choices": choices,
        "my_subjects": _my_subjects(request.user),
        "has_any_recommendations": bool(cached),
        "max_per_run": recommendations.MAX_SKILLS_PER_RUN,
        "default_photo": recommendations.DEFAULT_PHOTO,
    })


@login_required
@require_POST
def recommendations_generate_view(request):
    skills = [s.strip() for s in request.POST.getlist("skills") if s and s.strip()]
    skills = skills[:recommendations.MAX_SKILLS_PER_RUN]
    if not skills:
        return JsonResponse({"ok": False, "error": "Choose at least one skill."}, status=400)
    context = ""
    subject_value = _subject_code(request.POST.get("subject", ""))
    labels = dict(_subject_choices())
    labels.update(_my_subjects(request.user))
    if subject_value in labels:
        context = f"to teach within the university subject {labels[subject_value]}"
    try:
        out = recommendations.generate_for_skills(skills, "professor", context)
    except recommendations.RecommendationError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse({"ok": True, **out})


@login_required
def recommendations_download_view(request):
    path = recommendations.recs_path()
    if not path.is_file():
        raise Http404("No recommendations have been generated yet.")
    return FileResponse(open(path, "rb"), as_attachment=True, filename=path.name, content_type="text/csv")


@administrator_required
@require_POST
def developer_results_view(request):
    """The developer switches: Real / Dummy results ("results") and Faculty / Student / Alumni
    view ("view"). Each button sends only its own switch, so the other one keeps its setting."""
    from ..context_processors import DEV_DUMMY_VIEW_KEY, DEV_STUDENT_VIEW_KEY
    if not request.user.is_developer:
        raise PermissionDenied
    if "results" in request.POST:
        request.session[DEV_DUMMY_VIEW_KEY] = request.POST.get("results") == "dummy"
    if "view" in request.POST:
        view = request.POST.get("view")
        request.session[DEV_STUDENT_VIEW_KEY] = view if view in ("student", "alumni") else ""
    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect("dashboard")
