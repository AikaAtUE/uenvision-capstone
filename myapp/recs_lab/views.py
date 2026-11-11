"""Recommendations Lab pages. Developers only, and only by typing the link: anyone else
(logged in or not as a developer) gets a plain 404, as if the pages didn't exist."""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .. import job_roles
from ..context_processors import DEV_DUMMY_VIEW_KEY
from ..models import CurriculumSurveyResponse, CustomUser
from ..views.common import _sees_dummy_results
from . import blueprints, engine, gemini, taxonomy


def developer_only(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not getattr(request.user, "is_developer", False):
            raise Http404
        return view(request, *args, **kwargs)
    return wrapper


def _ctx(request, tab, **extra):
    return {"active_page": "", "lab_tab": tab, "lab_dummy": _sees_dummy_results(request), **extra}


def _back(request, fallback):
    nxt = request.POST.get("next") or ""
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect(fallback)


@developer_only
@require_POST
def data_switch_view(request):
    """Real / dummy answers for the lab (the same switch the Dashboard's developer view uses)."""
    request.session[DEV_DUMMY_VIEW_KEY] = request.POST.get("results") == "dummy"
    return _back(request, reverse("recs_lab"))


# ---------------------------------------------------------------------------
@developer_only
def index_view(request):
    dummy = _sees_dummy_results(request)
    bps = blueprints.all_blueprints()
    counts = {"approved": 0, "draft": 0, "auto": 0}
    for bp in bps.values():
        counts[bp["status"]] += 1
    resps = engine.responses(dummy)
    first = lambda t: next((r["user_id"] for r in resps if r["type"] == t and r["user_id"]), None)  # noqa: E731
    return render(request, "recs_lab/index.html", _ctx(
        request, "index", bp_counts=counts, subjects=len(bps),
        first_student=first(CurriculumSurveyResponse.STUDENT), first_alumni=first(CurriculumSurveyResponse.ALUMNI),
        n_resps={t: sum(1 for r in resps if r["type"] == t) for t in ("student", "alumni", "professor")}))


# ---------------------------------------------------------------------------
@developer_only
def faculty_view(request):
    dummy = _sees_dummy_results(request)
    subs = [s for s in blueprints.subjects()]
    code = request.GET.get("subject") or (subs[0]["code"] if subs else "")
    try:
        prof = int(request.GET.get("prof") or 0) or None
    except ValueError:
        prof = None
    result = engine.faculty_view(code, professor_id=prof, dummy=dummy) if code else {"exists": False}
    return render(request, "recs_lab/faculty.html", _ctx(
        request, "faculty", subjects=subs, code=code, prof=prof, result=result,
        professors=engine.professors_for(code, dummy) if code else []))


@developer_only
def admin_view(request):
    dummy = _sees_dummy_results(request)
    program = request.GET.get("program") if request.GET.get("program") in ("BSIT", "BSCS") else ""
    levels = "all" if request.GET.get("levels") == "all" else "entry"
    try:
        floor = max(0.5, min(25.0, float(request.GET.get("floor") or engine.DEFAULT_FLOOR)))
    except ValueError:
        floor = engine.DEFAULT_FLOOR
    kind = request.GET.get("kind") if request.GET.get("kind") in taxonomy.KINDS else ""
    result = engine.admin_gaps(program, entry_only=levels == "entry", floor=floor, dummy=dummy, limit=1000)
    rows = []
    if result.get("exists"):
        rows = [r for r in result["all_rows"] if not kind or r["kind"] == kind][:10]
    return render(request, "recs_lab/admin.html", _ctx(
        request, "admin", result=result, rows=rows, program=program, levels=levels, floor=floor, kind=kind,
        kinds=taxonomy.KINDS))


def _learner_choices(kind, dummy):
    rtype = CurriculumSurveyResponse.ALUMNI if kind == "alumni" else CurriculumSurveyResponse.STUDENT
    role = CustomUser.Role.ALUMNI if kind == "alumni" else CustomUser.Role.STUDENT
    ids = {r["user_id"] for r in engine.responses(dummy) if r["type"] == rtype and r["user_id"]}
    return list(CustomUser.objects.filter(pk__in=ids, role=role).order_by("last_name", "first_name"))


@developer_only
def learner_view(request, kind):
    dummy = _sees_dummy_results(request)
    people = _learner_choices(kind, dummy)
    try:
        pk = int(request.GET.get("user") or 0)
    except ValueError:
        pk = 0
    person = next((u for u in people if u.pk == pk), people[0] if people else None)
    result = None
    if person:
        result = engine.alumni_view(person, dummy) if kind == "alumni" else engine.student_view(person, dummy)
    return render(request, f"recs_lab/{kind}.html", _ctx(
        request, kind, people=people, person=person, result=result, roles=job_roles.ROLE_LABELS))


@developer_only
def student_view(request):
    return learner_view(request, "student")


@developer_only
def alumni_view(request):
    return learner_view(request, "alumni")


# ---------------------------------------------------------------------------
@developer_only
def blueprints_view(request):
    dummy = _sees_dummy_results(request)
    subs = blueprints.subjects()
    code = request.GET.get("subject") or request.POST.get("subject") or ""
    info = blueprints.subject(code) if code else None
    if request.method == "POST" and info:
        action = request.POST.get("action")
        url = f"{reverse('recs_lab_blueprints')}?subject={code}"
        try:
            if action == "save":
                bp, problems = blueprints.from_text(request.POST)
                for p in problems:
                    messages.error(request, p)
                if not problems:
                    blueprints.save(code, bp, status="draft", source="manual")
                    messages.success(request, "Blueprint saved as a draft.")
            elif action == "approve":
                blueprints.approve(code, request.user)
                messages.success(request, "Blueprint approved.")
            elif action == "reset":
                blueprints.reset(code)
                messages.success(request, "Blueprint reset to the automatic draft.")
            elif action == "gemini":
                reported = [r["names"][k] for r in engine.responses(dummy) for k in r["subjects"].get(code, {})]
                gemini.draft_blueprint(code, list(dict.fromkeys(reported)))
                messages.success(request, "Gemini drafted a new blueprint. Review it, then approve it.")
        except (ValueError, gemini.LabGeminiError) as e:
            messages.error(request, str(e))
        return redirect(url)
    bps = blueprints.all_blueprints()
    bp = bps.get(code) if info else None
    rows = [{**s, "status": bps[s["code"]]["status"], "core": len(bps[s["code"]]["core"]),
             "slots": len(bps[s["code"]]["slots"])} for s in subs]
    return render(request, "recs_lab/blueprints.html", _ctx(
        request, "blueprints", rows=rows, info=info, bp=bp, text=blueprints.to_text(bp) if bp else None,
        families=taxonomy.families(), targets=blueprints.TARGET_LABELS, code=code))


@developer_only
def skills_view(request):
    d = engine.demand("", entry_only=False)
    tagger = taxonomy.Tagger()
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "tag":
                taxonomy.set_tag(request.POST.get("skill", ""), request.POST.get("kind", ""),
                                 request.POST.get("family", ""), source="manual")
                messages.success(request, f"Saved the tag for {request.POST.get('skill', '')}.")
            elif action == "clear":
                taxonomy.clear_tag(request.POST.get("skill", ""))
                messages.success(request, "Tag reset to the built-in rules.")
            elif action == "family":
                taxonomy.add_family(request.POST.get("label", ""), request.POST.get("kind", ""))
                messages.success(request, "Family added.")
            elif action == "gemini" and d:
                untagged = [d["label"][k] for k, _c in sorted(d["counts"].items(), key=lambda kv: -kv[1])
                            if tagger(d["label"][k])["source"] == "rules"]
                res = gemini.tag_skills(untagged)
                messages.success(request, f"Gemini tagged {res['tagged']} skills"
                                 + (f" and added families: {', '.join(res['new_families'])}." if res["new_families"] else "."))
        except (ValueError, gemini.LabGeminiError) as e:
            messages.error(request, str(e))
        return _back(request, reverse("recs_lab_skills"))
    kind = request.GET.get("kind") if request.GET.get("kind") in taxonomy.KINDS else ""
    q = (request.GET.get("q") or "").strip().lower()
    rows = []
    if d:
        for k, c in sorted(d["counts"].items(), key=lambda kv: (-kv[1], d["label"][kv[0]].lower())):
            name = d["label"][k]
            t = tagger(name)
            if (kind and t["kind"] != kind) or (q and q not in name.lower()):
                continue
            rows.append({"skill": name, "pct": d["pct"][k], "count": c, **t})
    editing = None
    edit_name = (request.GET.get("edit") or "").strip()
    if edit_name and d:
        hit = next((d["label"][k] for k in d["counts"] if d["label"][k] == edit_name), None)
        if hit:
            editing = {"skill": hit, **tagger(hit)}
    by_source = {}
    if d:
        for k in d["counts"]:
            s = tagger(d["label"][k])["source"]
            by_source[s] = by_source.get(s, 0) + 1
    return render(request, "recs_lab/skills.html", _ctx(
        request, "skills", rows=rows[:300], total=len(rows), editing=editing, kinds=taxonomy.KINDS, kind=kind, q=request.GET.get("q", ""),
        families=taxonomy.families(), by_source=by_source, postings=d["postings"] if d else 0,
        max_batch=gemini.MAX_TAG_BATCH))
