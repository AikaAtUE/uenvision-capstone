"""
UEnvision — the public side of the site and the student/alumni side:

* home: public homepage with the top in-demand skills, overall and per job role
* check_gap: "are you a student or a fresh graduate?" -> registration -> the survey
* skill_search / skill_add: the survey skill pickers' ontology search (public)
* register: a student/alumni creates their account (with their personal information,
  by email + password or with Google; students must use their UE email, alumni may
  use any email since they may no longer have their UE account) before answering their survey; after the
  survey they go to their dashboard. (Old "create your account" links from surveys
  answered before this, ?t=..., still work for their 3 days.)
* student_dashboard (+ role / generate): a student's or alumni's own skill gap
  against their chosen job role, with Gemini-found learning resources
* my_skills (+ save): a user's own subject -> skills record, editable any time --
  students/alumni and faculty/administrators alike rate each skill Introduced /
  Practiced / Applied (faculty edit theirs on the Professor Survey page). It edits their latest survey
  response in place, and only that latest response counts (here, on the
  Recommendations page and in the gap analysis), so an edit replaces, never adds.
"""
import json
from datetime import datetime, timezone

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import curriculum_data, email_verification, feedback_nudge, gap_analysis, job_roles, ontology, recommendations, skills_catalog
from .models import MIN_PASSWORD_LENGTH, CurriculumSurveyResponse, CustomUser

REGISTER_SALT = "uenvision-register"
REGISTER_MAX_AGE = 3 * 24 * 3600   # a survey's "create your account" link works for 3 days
TOP_SKILLS = 10
MAX_TO_BUILD = 6
# Practiced or Applied counts as "have it"; Introduced is still "building". (Older answers
# rated Beginner..Expert: Intermediate or better counts as "have it".)
STRONG_WEIGHT = 0.5


# ---------------------------------------------------------------------------
# Public homepage
# ---------------------------------------------------------------------------
def home_view(request):
    role = request.GET.get("role", "")
    program = request.GET.get("program", "")
    if program not in job_roles.PROGRAM_COLUMNS:
        program = ""
    stats = job_roles.skill_stats(role, TOP_SKILLS, program)
    if stats.get("exists"):
        top = stats["overall"]["skills"][0]["count"] if stats["overall"]["skills"] else 1
        for s in stats["overall"]["skills"]:
            s["bar"] = round(s["count"] / top * 100)
        if stats["role"]:
            rtop = max([s["pct"] for s in stats["role"]["skills"]] or [1])
            for s in stats["role"]["skills"]:
                s["bar"] = round(s["pct"] / rtop * 100)
    return render(request, "home.html", {"stats": stats, "role": role, "program": program,
                                         "programs": job_roles.PROGRAM_NAMES.items()})


def role_skills_view(request):
    """JSON version of the homepage numbers: ?role=<key>&top=<n>."""
    try:
        top = max(1, min(int(request.GET.get("top", TOP_SKILLS)), 30))
    except ValueError:
        return JsonResponse({"ok": False, "error": "Bad number."}, status=400)
    program = request.GET.get("program", "")
    if program not in job_roles.PROGRAM_COLUMNS:
        program = ""
    return JsonResponse({"ok": True, **job_roles.skill_stats(request.GET.get("role", ""), top, program)})


def check_gap_view(request):
    role = request.GET.get("role", "")
    if role not in job_roles.ROLE_LABELS:
        role = ""
    user = request.user
    learner_survey = None
    if user.is_authenticated and user.is_learner:
        learner_survey = reverse("alumni_survey" if user.role == CustomUser.Role.ALUMNI else "student_survey")
    return render(request, "check_gap.html", {"role": role, "role_label": job_roles.ROLE_LABELS.get(role, ""),
                                              "learner_survey": learner_survey})


# ---------------------------------------------------------------------------
# Skill search / add (survey pickers)
# ---------------------------------------------------------------------------
def skill_search_view(request):
    q = request.GET.get("q", "")[:skills_catalog.MAX_SKILL_LENGTH]
    skills_catalog.ensure_curated()
    return JsonResponse({"ok": True, "results": skills_catalog.search(q, 8)})


@require_POST
def skill_add_view(request):
    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"ok": False, "error": "Malformed request."}, status=400)
    name, created, error = skills_catalog.add_custom_skill(str(payload.get("name") or ""))
    if error:
        return JsonResponse({"ok": False, "error": error}, status=400)
    return JsonResponse({"ok": True, "name": name, "created": created})


# ---------------------------------------------------------------------------
# Registration after the survey
# ---------------------------------------------------------------------------
def register_url_for(response):
    token = signing.dumps({"r": response.pk}, salt=REGISTER_SALT)
    return reverse("register") + "?t=" + token


def _response_from_token(token):
    try:
        data = signing.loads(token, salt=REGISTER_SALT, max_age=REGISTER_MAX_AGE)
    except signing.BadSignature:   # includes SignatureExpired
        return None
    return CurriculumSurveyResponse.objects.filter(
        pk=data.get("r"),
        respondent_type__in=[CurriculumSurveyResponse.STUDENT, CurriculumSurveyResponse.ALUMNI],
    ).first()


def _split_name(full):
    parts = str(full or "").split()
    if len(parts) < 2:
        return (parts[0] if parts else ""), ""
    return " ".join(parts[:-1]), parts[-1]


LEARNER_KINDS = {"student": CustomUser.Role.STUDENT, "alumni": CustomUser.Role.ALUMNI}
MAX_STUDENT_NUMBER_LENGTH = 30
MAX_NAME_LENGTH = 100
MIN_GRAD_YEAR = 2000
PASSWORD_BACKEND = "django.contrib.auth.backends.ModelBackend"


def survey_url_for(kind, target_role=""):
    url = reverse("alumni_survey" if kind == "alumni" else "student_survey")
    return url + (f"?role={target_role}" if target_role in job_roles.ROLE_LABELS else "")


def max_grad_year():
    return datetime.now(timezone.utc).year


def clean_learner_info(kind, post):
    """The personal information a student / alumni gives when registering (and may fix on
    their survey's "About you"). -> (info dict, error message or None)."""
    from .views.surveys import MAX_SECTION_LENGTH

    info = {"student_number": " ".join(str(post.get("student_number") or "").split()),
            "course": str(post.get("course") or "")}
    if not info["student_number"]:
        return info, "Please enter your student number."
    if len(info["student_number"]) > MAX_STUDENT_NUMBER_LENGTH:
        return info, "That student number is too long."
    if info["course"] not in curriculum_data.PROGRAM_LABELS:
        return info, "Please choose your course."
    if kind == "student":
        year = str(post.get("year_level") or "")
        info["year_level"] = year
        info["section"] = " ".join(str(post.get("section") or "").split())
        if not year.isdigit() or int(year) not in curriculum_data.YEAR_LEVELS:
            return info, "Please choose your year level."
        if not info["section"]:
            return info, "Please enter your section."
        if len(info["section"]) > MAX_SECTION_LENGTH:
            return info, "That section is too long."
    else:
        grad = str(post.get("year_graduated") or "").strip()
        info["year_graduated"] = grad
        if not grad.isdigit() or not MIN_GRAD_YEAR <= int(grad) <= max_grad_year():
            return info, f"Please enter the year you graduated ({MIN_GRAD_YEAR}-{max_grad_year()})."
    return info, None


def _valid_email(email):
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email
    try:
        validate_email(email)
    except ValidationError:
        return False
    return True


def register_view(request):
    token = request.GET.get("t") or request.POST.get("t") or ""
    if token:
        return _register_after_survey(request, token)
    from . import google_auth

    kind = request.GET.get("as") or request.POST.get("as") or ""
    if kind not in LEARNER_KINDS:
        return redirect("check_gap")
    target_role = request.GET.get("role") or request.POST.get("role") or ""
    if target_role not in job_roles.ROLE_LABELS:
        target_role = ""
    user = request.user
    if user.is_authenticated:
        if user.is_learner:
            return redirect(survey_url_for("alumni" if user.role == CustomUser.Role.ALUMNI else "student", target_role))
        return redirect("home")

    ctx = {"kind": kind, "target_role": target_role, "role_label": job_roles.ROLE_LABELS.get(target_role, ""),
           "programs": curriculum_data.PROGRAM_LABELS.items(), "year_levels": curriculum_data.YEAR_LEVELS,
           "min_grad_year": MIN_GRAD_YEAR, "max_grad_year": max_grad_year(),
           "min_password_length": MIN_PASSWORD_LENGTH, "google_enabled": google_auth.google_enabled(),
           "ue_email_domain": google_auth.UE_EMAIL_DOMAIN, "form": {}}
    if request.method != "POST":
        return render(request, "register.html", ctx)

    post = request.POST
    with_google = post.get("method") == "google" and google_auth.google_enabled()
    first = " ".join(str(post.get("first_name") or "").split())[:MAX_NAME_LENGTH]
    last = " ".join(str(post.get("last_name") or "").split())[:MAX_NAME_LENGTH]
    email = str(post.get("email") or "").strip()
    password, password2 = post.get("password", ""), post.get("password2", "")
    info, error = clean_learner_info(kind, post)
    if not error and (not first or not last):
        error = "Please enter your first and last name."
    if not error and post.get("consent") != "on":
        error = "Please tick the box to agree to the Data Privacy Notice."
    if not error and not with_google:
        if kind == "student" and not google_auth.is_ue_email(email):
            error = f"Please use your UE email address (ending in @{google_auth.UE_EMAIL_DOMAIN})."
        elif not _valid_email(email):
            error = "Please enter a valid email address."
        elif CustomUser.objects.filter(email__iexact=email).exists():
            error = "An account with this email already exists. Please log in instead."
        elif len(password) < MIN_PASSWORD_LENGTH:
            error = f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        elif password != password2:
            error = "Passwords do not match."
    if error:
        # what they typed stays in the form (never the passwords), so only the problem needs fixing
        form = {k: v for k, v in post.items() if k not in ("password", "password2", "csrfmiddlewaretoken")}
        return render(request, "register.html", {**ctx, "error": error, "form": form})

    if with_google:
        # Google confirms the email; google_auth.SocialAccountAdapter makes the account.
        request.session[google_auth.PENDING_KEY] = {"role": kind, "first_name": first, "last_name": last,
                                                    "info": info, "target_role": target_role}
        return google_auth.start_google_login(request, next_url=survey_url_for(kind, target_role))

    user = CustomUser.objects.create_user(
        email=email, password=password, first_name=first, last_name=last, role=LEARNER_KINDS[kind],
        target_role=target_role, learner_info=info,
        email_verified=not email_verification.verification_required(),
    )
    if not user.email_verified:
        # They can use UEnvision right away; the dashboard reminds them to confirm.
        email_verification.send_verification_email(request, user)
    login(request, user, backend=PASSWORD_BACKEND)
    return redirect(survey_url_for(kind, target_role))


def _register_after_survey(request, token):
    """Old flow: a survey answered before registering came first, with a signed link."""
    response = _response_from_token(token)
    if response is None:
        return render(request, "register_link.html", {"invalid": True})
    if response.user_id:
        return render(request, "register_link.html", {"already": True})
    info = response.data.get("personal_info") or {}
    survey_email = str(info.get("ue_email") or "").strip()
    ctx = {"token": token, "email": survey_email, "name": info.get("name", ""),
           "min_password_length": MIN_PASSWORD_LENGTH}
    if request.method != "POST":
        return render(request, "register_link.html", ctx)

    email = request.POST.get("email", "").strip()
    password = request.POST.get("password", "")
    password2 = request.POST.get("password2", "")
    error = None
    if email.lower() != survey_email.lower():
        error = "Please type the same UE email address you used in the survey."
    elif CustomUser.objects.filter(email__iexact=email).exists():
        error = "An account with this email already exists. Please log in instead."
    elif len(password) < MIN_PASSWORD_LENGTH:
        error = f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    elif password != password2:
        error = "Passwords do not match."
    if error:
        return render(request, "register_link.html", {**ctx, "error": error, "form": request.POST})

    first, last = _split_name(info.get("name"))
    role = (CustomUser.Role.ALUMNI if response.respondent_type == CurriculumSurveyResponse.ALUMNI
            else CustomUser.Role.STUDENT)
    keep = ("student_number", "course", "year_level", "section", "year_graduated")
    user = CustomUser.objects.create_user(
        email=survey_email, password=password, first_name=first or survey_email.split("@")[0],
        last_name=last, role=role, target_role=response.data.get("target_role") or "",
        learner_info={k: str(info[k]) for k in keep if info.get(k) not in (None, "")},
        email_verified=not email_verification.verification_required(),
    )
    response.user = user
    response.save(update_fields=["user"])
    if not user.email_verified:
        email_verification.send_verification_email(request, user)
    login(request, user, backend=PASSWORD_BACKEND)
    return redirect("student_dashboard")


# ---------------------------------------------------------------------------
# Student / alumni dashboard
# ---------------------------------------------------------------------------
def latest_response(user):
    """The user's current subject/skills record: their most recent survey response
    (student/alumni survey for learners, Professor Survey for faculty/administrators)."""
    types = ([CurriculumSurveyResponse.STUDENT, CurriculumSurveyResponse.ALUMNI] if user.is_learner
             else [CurriculumSurveyResponse.PROFESSOR])
    return (CurriculumSurveyResponse.objects.filter(user=user, respondent_type__in=types)
            .order_by("-created_at", "-pk").first())


def _my_skills(user):
    """{skill_key: {"skill", "weight", "level"}} from the user's current record (latest
    survey response, possibly edited on My subjects & skills); a skill keeps the
    highest level reported for it."""
    mine = {}
    latest = latest_response(user)
    for data in ([latest.data] if latest else []):
        entries = []
        for subj in (data or {}).get("subjects") or []:
            if isinstance(subj, dict):
                entries.extend(subj.get("skills") or [])
        entries.extend((data or {}).get("overall_skills") or [])
        for name, level in gap_analysis._skill_entries(entries):
            hit = gap_analysis._standardize(name)
            if not hit:
                continue
            w = gap_analysis.level_weight(level)
            prev = mine.get(hit[0])
            if prev is None or w > prev["weight"]:
                mine[hit[0]] = {"skill": hit[1], "weight": w, "level": str(level or "").title()}
    return mine


def _status(mine, key):
    m = mine.get(key)
    if not m:
        return "missing", ""
    return ("strong" if m["weight"] >= STRONG_WEIGHT else "building"), m["level"]


@login_required
def student_dashboard_view(request):
    user = request.user
    feedback_nudge.record_use(user)
    has_survey = CurriculumSurveyResponse.objects.filter(user=user).exists()
    mine = _my_skills(user)
    stats = job_roles.skill_stats(user.target_role, TOP_SKILLS)
    role = stats.get("role") if stats.get("exists") else None
    compare = (role["skills"] if role else stats["overall"]["skills"]) if stats.get("exists") else []
    for s in compare:
        s["status"], s["my_level"] = _status(mine, s["key"])
    overall = stats["overall"]["skills"] if stats.get("exists") else []
    for s in overall:
        s["status"], s["my_level"] = _status(mine, s["key"])

    have = sum(1 for s in compare if s["status"] == "strong")
    readiness = round(have / len(compare) * 100) if compare else None
    to_build = [s for s in compare if s["status"] != "strong"][:MAX_TO_BUILD]
    cached = recommendations.load_recommendations("student")
    for s in to_build:
        s["cached_resources"] = cached.get(s["skill"].strip().lower(), [])

    return render(request, "student_dashboard.html", {
        "active_page": "student_dashboard",
        "has_survey": has_survey,
        "survey_url": reverse("alumni_survey" if user.role == CustomUser.Role.ALUMNI else "student_survey"),
        "stats": stats,
        "role": role,
        "roles": stats.get("roles", []) if stats.get("exists") else [],
        "compare": compare,
        "overall": overall,
        "readiness": readiness,
        "have": have,
        "to_build": to_build,
        "my_skills": sorted(mine.values(), key=lambda m: (-m["weight"], m["skill"].lower())),
        "max_per_run": recommendations.MAX_SKILLS_PER_STUDENT_RUN,
        "default_photo": recommendations.DEFAULT_PHOTO,
    })


@login_required
@require_POST
def student_role_view(request):
    role = request.POST.get("role", "")
    request.user.target_role = role if role in job_roles.ROLE_LABELS else ""
    request.user.save(update_fields=["target_role"])
    return redirect("student_dashboard")


@login_required
@require_POST
def student_generate_view(request):
    feedback_nudge.record_use(request.user)
    skills = [s.strip() for s in request.POST.getlist("skills") if s and s.strip()]
    skills = skills[:recommendations.MAX_SKILLS_PER_STUDENT_RUN]
    if not skills:
        return JsonResponse({"ok": False, "error": "Choose at least one skill."}, status=400)
    role = job_roles.ROLE_LABELS.get(request.user.target_role, "")
    context = f"the learner wants to work as a {role}" if role else ""
    try:
        out = recommendations.generate_for_skills(skills, "student", context)
    except recommendations.RecommendationError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse({"ok": True, **out})


# ---------------------------------------------------------------------------
# My subjects & skills (editable survey record)
# ---------------------------------------------------------------------------
# Students and alumni rate their skills with the same Introduced / Practiced / Applied
# levels as the Professor Survey. Answers saved before used beginner..expert; those still
# count (gap_analysis.LEVEL_WEIGHTS) but must be re-rated when the record is edited.
PROFESSOR_LEVELS = {"introduced", "practiced", "applied"}
LEARNER_LEVELS = PROFESSOR_LEVELS
MAX_EDIT_SUBJECTS = 80
MAX_EDIT_SKILLS = 40
MAX_EDIT_BODY = 300_000


def _subject_options(program, professor=False):
    """[{"label": term label, "subjects": [{"code", "name"}]}] for the "add a subject"
    picker: the learner's own curriculum, or both when the program is unknown (and
    always both for professors, minus the subjects they advise rather than teach)."""
    if professor:
        return _professor_subject_options()
    programs = [program] if program in curriculum_data.PROGRAMS else list(curriculum_data.PROGRAMS)
    groups = []
    seen = set()
    for prog in programs:
        for term in curriculum_data.term_sequence(prog):
            subs = []
            for subj in curriculum_data.learner_subjects_for_term(prog, term["key"]):
                if subj["code"] in seen:
                    continue
                seen.add(subj["code"])
                subs.append({"code": subj["code"], "name": subj["name"]})
            if subs:
                label = term["label"] if len(programs) == 1 else f"{prog} · {term['label']}"
                groups.append({"label": label, "subjects": subs})
    return groups


_YEAR_NAMES = {1: "1st Year", 2: "2nd Year", 3: "3rd Year", 4: "4th Year"}
_SEM_NAMES = {1: "1st Semester", 2: "2nd Semester", 3: "Summer"}


def _professor_subject_options():
    """Both curricula in one list, Year -> Sem -> Course (BSIT first; a subject both
    programs share sits where BSIT has it), minus the subjects professors don't teach."""
    tags = curriculum_data.subject_term_tags()
    groups = {}
    for code, info in curriculum_data.subject_by_code().items():
        if code in curriculum_data.HIDDEN_FROM_PROFESSORS:
            continue
        year, sem, _, _ = key = curriculum_data.subject_sort_key(code, tags)
        groups.setdefault((year, sem), []).append((key, {"code": code, "name": info["name"]}))
    return [{"label": f"{_YEAR_NAMES.get(year, f'Year {year}')} – {_SEM_NAMES[sem]}",
             "subjects": [subj for _, subj in sorted(items, key=lambda x: x[0])]}
            for (year, sem), items in sorted(groups.items())]


def _clean_skills(raw, levels=LEARNER_LEVELS):
    """[{"name", "level"}] -> cleaned list, or None if malformed."""
    if not isinstance(raw, list) or len(raw) > MAX_EDIT_SKILLS:
        return None
    out, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            return None
        name = " ".join(str(item.get("name") or "").split())[:skills_catalog.MAX_SKILL_LENGTH]
        level = str(item.get("level") or "").lower()
        if not name or level not in levels:
            return None
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append({"name": name, "level": level})
    return out


@login_required
def my_skills_view(request):
    user = request.user
    from . import views

    if not user.is_learner:
        return redirect("professor_survey")   # professors edit their record on the Professor Survey page
    response = latest_response(user)
    is_alumni = user.role == CustomUser.Role.ALUMNI
    professor = not user.is_learner
    ctx = {"active_page": "data" if professor else "my_skills", "data_tab": "my_skills",
           "professor": professor, "has_record": response is not None,
           "survey_url": reverse("professor_survey" if professor
                                 else "alumni_survey" if is_alumni else "student_survey")}
    if response is None:
        return render(request, "my_skills.html", ctx)
    data = response.data or {}
    program = str((data.get("personal_info") or {}).get("course") or "")
    by_code = curriculum_data.subject_by_code()
    subjects = []
    for subj in data.get("subjects") or []:
        if isinstance(subj, dict) and subj.get("code"):
            subjects.append({"code": subj["code"],
                             "name": subj.get("name") or by_code.get(subj["code"], {}).get("name", ""),
                             "custom": bool(subj.get("custom")), "programs": subj.get("programs") or [],
                             "skills": [s for s in (subj.get("skills") or []) if isinstance(s, dict)]})
    bootstrap = {
        "mode": "my_skills",
        "isAlumni": is_alumni,
        "levels": "ipa" if professor else "learner_ipa",
        "subjects": subjects,
        "overallSkills": [s for s in (data.get("overall_skills") or []) if isinstance(s, dict)],
        "subjectOptions": _subject_options(program, professor),
        "knownCodes": sorted(by_code),
        "skills": ontology.subject_skill_map(),
        "termTags": curriculum_data.subject_term_tags(),
        "saveUrl": reverse("my_skills_save"),
        "skillSearchUrl": reverse("skill_search"),
        "skillAddUrl": reverse("skill_add"),
    }
    ctx.update({
        "program_label": curriculum_data.PROGRAM_LABELS.get(program, program),
        "edited_at": data.get("edited_at"),
        "submitted_at": response.created_at,
        "bootstrap_json": views._safe_json(bootstrap),   # escapes </script> etc. in user-typed skill names
    })
    return render(request, "my_skills.html", ctx)


@login_required
@require_POST
def my_skills_save_view(request):
    response = latest_response(request.user)
    if response is None:
        return JsonResponse({"ok": False, "error": "Answer the survey first."}, status=400)
    if len(request.body or b"") > MAX_EDIT_BODY:
        return JsonResponse({"ok": False, "error": "That is too large."}, status=400)
    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"ok": False, "error": "Malformed request."}, status=400)
    if not isinstance(payload, dict) or not isinstance(payload.get("subjects"), list):
        return JsonResponse({"ok": False, "error": "Malformed request."}, status=400)
    if len(payload["subjects"]) > MAX_EDIT_SUBJECTS:
        return JsonResponse({"ok": False, "error": "Too many subjects."}, status=400)

    by_code = curriculum_data.subject_by_code()
    professor = not request.user.is_learner
    levels = PROFESSOR_LEVELS if professor else LEARNER_LEVELS
    old = {s.get("code"): s for s in (response.data.get("subjects") or []) if isinstance(s, dict)}
    learner_program = str(((response.data or {}).get("personal_info") or {}).get("course") or "")
    subjects, seen = [], set()
    for entry in payload["subjects"]:
        code = str((entry or {}).get("code") or "") if isinstance(entry, dict) else ""
        if entry.get("custom"):
            # a subject they added because it isn't in the list (an elective, ...)
            fields, error = (curriculum_data.clean_custom_subject(entry) if professor else
                             curriculum_data.clean_learner_custom_subject(entry, learner_program))
            if error:
                return JsonResponse({"ok": False, "error": error}, status=400)
            code = fields["code"]
        elif code not in by_code or (professor and code in curriculum_data.HIDDEN_FROM_PROFESSORS and code not in old):
            return JsonResponse({"ok": False, "error": "Unknown subject."}, status=400)
        else:
            fields = {"code": code, "name": by_code[code]["name"]}
        if code in seen:
            continue
        seen.add(code)
        skills = _clean_skills(entry.get("skills"), levels)
        if skills is None:
            return JsonResponse({"ok": False, "error": f"Please choose a level for every skill in {code}."}, status=400)
        prev = old.get(code, {})
        subjects.append({**prev, **fields, "term": prev.get("term") or "added", "skills": skills})

    data = dict(response.data)
    data["subjects"] = subjects
    if request.user.role == CustomUser.Role.ALUMNI and "overall_skills" in payload:
        overall = _clean_skills(payload.get("overall_skills"))
        if overall is None:
            return JsonResponse({"ok": False, "error": "Please choose a level for every overall skill."}, status=400)
        data["overall_skills"] = overall
    data["edited_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    response.data = data
    response.save(update_fields=["data"])
    return JsonResponse({"ok": True, "edited_at": data["edited_at"]})
