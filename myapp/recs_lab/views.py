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
from . import blueprints, engine, gemini, resources, tagjob, taxonomy, worker


# Who can open which lab page. Developers see everything and can switch between accounts.
# Dummy (test) accounts see the lab the way that kind of account would: a dummy student only
# their own Student page, a dummy professor only their own subjects, a dummy administrator the
# Admin, Faculty and Blueprint pages. Real (non-dummy) accounts never see the lab at all.
PAGES = {
    "developer": {"dev", "index", "faculty", "admin", "student", "alumni", "blueprints", "skills", "resources"},
    "student": {"student"},
    "alumni": {"alumni"},
    "faculty": {"faculty"},
    "admin": {"admin", "faculty", "blueprints"},
}
HOME = {"student": "recs_lab_student", "alumni": "recs_lab_alumni", "faculty": "recs_lab_faculty",
        "admin": "recs_lab_admin"}


def lab_role(user):
    """"developer", "student", "alumni", "faculty", "admin" (dummy accounts), or None (no access)."""
    if not getattr(user, "is_authenticated", False):
        return None
    if user.is_developer:
        return "developer"
    if not user.is_dummy:
        return None
    return {CustomUser.Role.STUDENT: "student", CustomUser.Role.ALUMNI: "alumni",
            CustomUser.Role.FACULTY: "faculty", CustomUser.Role.ADMINISTRATOR: "admin"}.get(user.role)


def lab_page(page):
    """Only the lab roles whose PAGES include `page`; everyone else gets a plain 404."""
    def deco(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            role = lab_role(request.user)
            if role is None:
                raise Http404
            if page not in PAGES[role]:
                if page == "index":
                    return redirect(HOME[role])
                raise Http404
            request.lab_role = role
            return view(request, *args, **kwargs)
        return wrapper
    return deco


developer_only = lab_page("dev")   # the Real / Dummy switch, which only developers have


def _ctx(request, tab, **extra):
    role = getattr(request, "lab_role", None) or lab_role(request.user)
    return {"active_page": "", "lab_tab": tab, "lab_dummy": _sees_dummy_results(request), "lab_role": role,
            "lab_pages": PAGES.get(role, set()), "lab_is_dev": role == "developer", **extra}


def _back(request, fallback):
    nxt = request.POST.get("next") or ""
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect(fallback)


def _resources_step(request, specs):
    """Handles the page's "Find resources" button and returns the context for the resource bar.
    -> (redirect response or None, context dict)."""
    if request.method == "POST" and request.POST.get("action") == "find_resources":
        n = worker.enqueue(specs)
        worker.start()
        if n:
            messages.success(request, f"Looking for resources for {n} item{'s' if n != 1 else ''} in the background. "
                                      "This page refreshes by itself while it works (about 15 seconds each).")
        elif worker.status({s["key"] for s in specs})["pending"]:
            messages.info(request, "Already looking for this page's resources.")
        else:
            messages.info(request, "Everything on this page already has resources saved.")
        return redirect(request.get_full_path()), {}
    keys = {s["key"] for s in specs}
    have = resources.saved()
    st = worker.status(keys)
    return None, {"res_missing": sum(1 for k in keys if k not in have), "res_total": len(keys), "res_status": st,
                  "free_only": request.GET.get("free") == "1"}


@developer_only
@require_POST
def data_switch_view(request):
    """Real / dummy answers for the lab (the same switch the Dashboard's developer view uses)."""
    request.session[DEV_DUMMY_VIEW_KEY] = request.POST.get("results") == "dummy"
    return _back(request, reverse("recs_lab"))


# ---------------------------------------------------------------------------
@lab_page("index")
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
@lab_page("faculty")
def faculty_view(request):
    dummy = _sees_dummy_results(request)
    subs = [s for s in blueprints.subjects()]
    own_only = request.lab_role == "faculty"
    mine = []
    if own_only:
        # a (dummy) professor sees it as themselves, for the subjects of their Professor Survey
        prof = request.user.pk
        taught = {c for r in engine.responses(dummy) if r["type"] == CurriculumSurveyResponse.PROFESSOR
                  and r["user_id"] == prof for c in r["subjects"]}
        mine = [s for s in subs if s["code"] in taught]
        subs = mine or subs
    code = request.GET.get("subject") if any(s["code"] == request.GET.get("subject") for s in subs) else (
        subs[0]["code"] if subs else "")
    if not own_only:
        try:
            prof = int(request.GET.get("prof") or 0) or None
        except ValueError:
            prof = None
    result = engine.faculty_view(code, professor_id=prof, dummy=dummy) if code else {"exists": False}
    specs = resources.plan_faculty(result) if result.get("exists") else []
    resp, res = _resources_step(request, specs)
    if resp:
        return resp
    return render(request, "recs_lab/faculty.html", _ctx(
        request, "faculty", subjects=subs, code=code, prof=prof, result=result, own_only=own_only,
        no_survey=own_only and not mine,
        professors=[] if own_only else (engine.professors_for(code, dummy) if code else []), **res))


@lab_page("admin")
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
    resp, res = _resources_step(request, resources.plan_admin(rows))
    if resp:
        return resp
    return render(request, "recs_lab/admin.html", _ctx(
        request, "admin", result=result, rows=rows, program=program, levels=levels, floor=floor, kind=kind,
        kinds=taxonomy.KINDS, **res))


def _learner_choices(kind, dummy):
    rtype = CurriculumSurveyResponse.ALUMNI if kind == "alumni" else CurriculumSurveyResponse.STUDENT
    role = CustomUser.Role.ALUMNI if kind == "alumni" else CustomUser.Role.STUDENT
    ids = {r["user_id"] for r in engine.responses(dummy) if r["type"] == rtype and r["user_id"]}
    return list(CustomUser.objects.filter(pk__in=ids, role=role).order_by("last_name", "first_name"))


def learner_view(request, kind):
    dummy = _sees_dummy_results(request)
    self_only = request.lab_role == kind          # a dummy student / alumni sees it as themselves
    if self_only and request.method == "POST" and request.POST.get("action") == "set_role":
        role = request.POST.get("role", "")
        request.user.target_role = role if role in job_roles.ROLE_LABELS else ""
        request.user.save(update_fields=["target_role"])
        messages.success(request, "Target role saved." if request.user.target_role else "Target role cleared.")
        return redirect(request.get_full_path())
    if self_only:
        people, person = [], request.user
        preview = None
    else:
        people = _learner_choices(kind, dummy)
        try:
            pk = int(request.GET.get("user") or 0)
        except ValueError:
            pk = 0
        person = next((u for u in people if u.pk == pk), people[0] if people else None)
        # developers try another role without changing the account's saved one
        preview = request.GET.get("role") if request.GET.get("role") in job_roles.ROLE_LABELS else None
    result = None
    specs = []
    free_only = request.GET.get("free") == "1"
    if person:
        view = engine.alumni_view if kind == "alumni" else engine.student_view
        result = view(person, dummy, role=preview)
        if result.get("exists"):
            specs = (resources.plan_alumni if kind == "alumni" else resources.plan_student)(result, free_only)
    resp, res = _resources_step(request, specs)
    if resp:
        return resp
    return render(request, f"recs_lab/{kind}.html", _ctx(
        request, kind, people=people, person=person, result=result, roles=job_roles.ROLE_LABELS,
        self_only=self_only, preview=preview, **res))


@lab_page("student")
def student_view(request):
    return learner_view(request, "student")


@lab_page("alumni")
def alumni_view(request):
    return learner_view(request, "alumni")


# ---------------------------------------------------------------------------
@lab_page("blueprints")
def blueprints_view(request):
    code = request.GET.get("subject") or request.POST.get("subject") or ""
    if request.method == "POST":
        blueprint_action(request, code, _sees_dummy_results(request))
        return redirect(f"{reverse('recs_lab_blueprints')}?subject={code}")
    return render(request, "recs_lab/blueprints.html", _ctx(
        request, "blueprints", **blueprint_context(code), bp_url=reverse("recs_lab_blueprints") + "?",
        faculty_url=reverse("recs_lab_faculty") + "?"))


def blueprint_action(request, code, dummy):
    """The blueprint editor's buttons (save / approve / reset / Draft with Gemini), shared by the lab and the
    administrators' Recommendations page. Messages say what happened."""
    if not blueprints.subject(code):
        return
    action = request.POST.get("action")
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


def blueprint_context(code):
    """The blueprint list, or one subject's blueprint and its editor text."""
    info = blueprints.subject(code) if code else None
    bps = blueprints.all_blueprints()
    bp = bps.get(code) if info else None
    rows = [{**s, "status": bps[s["code"]]["status"], "core": len(bps[s["code"]]["core"]),
             "slots": len(bps[s["code"]]["slots"])} for s in blueprints.subjects()]
    return {"rows": rows, "info": info, "bp": bp, "text": blueprints.to_text(bp) if bp else None,
            "families": taxonomy.families(), "targets": blueprints.TARGET_LABELS, "code": code}


@lab_page("skills")
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
                if tagjob.start():
                    messages.success(request, "Tagging every rule-tagged skill with Gemini in the background, "
                                              f"{gemini.MAX_TAG_BATCH} at a time. This page shows the progress.")
                else:
                    messages.info(request, "Tagging is already running.")
            elif action == "gemini_stop":
                tagjob.stop()
                messages.info(request, "Tagging will stop after the current batch.")
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
        max_batch=gemini.MAX_TAG_BATCH, tag_job=tagjob.state()))


# ---------------------------------------------------------------------------
@lab_page("resources")
def resources_view(request):
    """Every saved resource request: refresh one, hide a bad resource, or clear the queue."""
    if request.method == "POST":
        action, k = request.POST.get("action"), request.POST.get("key", "")
        entry = resources.saved().get(k) or worker.jobs().get(k)
        if action == "refresh" and entry:
            worker.requeue({"key": k, "purpose": entry["purpose"], "skill": entry["skill"],
                            "context": entry.get("context", "")})
            worker.start()
            messages.success(request, f"Finding resources for {entry['skill']} again in the background.")
        elif action == "delete" and k:
            resources.delete_entry(k)
            worker.drop(k)
            messages.success(request, "Removed.")
        elif action == "hide" and k:
            resources.hide_item(k, request.POST.get("link", ""))
            messages.success(request, "That resource won't be shown again.")
        elif action == "run":
            messages.info(request, "Started." if worker.start() else "Already running.")
        elif action == "clear_failed":
            for jk, j in worker.jobs().items():
                if j["status"] == "failed":
                    worker.drop(jk)
            messages.success(request, "Cleared the failed requests.")
        return _back(request, reverse("recs_lab_resources"))
    who = request.GET.get("who") if request.GET.get("who") in ("learner", "professor") else ""
    entries = []
    for k, e in resources.saved().items():
        aud, label = resources.PURPOSES.get(e.get("purpose"), ("", ""))
        if who and aud != who:
            continue
        entries.append({"key": k, "audience": aud, "label": label, **e,
                        "shown": [i for i in e.get("items") or [] if not i.get("hidden")]})
    entries.sort(key=lambda e: e.get("generated_at", ""), reverse=True)
    queue = sorted(worker.jobs().items(), key=lambda kv: kv[1].get("queued_at", ""))
    return render(request, "recs_lab/resources.html", _ctx(
        request, "resources", entries=entries, queue=[{"key": k, **j} for k, j in queue], who=who,
        status=worker.status(), purposes=resources.PURPOSES))
