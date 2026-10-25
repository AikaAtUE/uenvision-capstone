"""Data > Survey Responses (administrators only): search, view and delete the
Student / Alumni / Professor curriculum survey answers (CurriculumSurveyResponse).

Search runs in Python over a short text built from each response (name, emails,
student number, course, subjects and skills) -- a few thousand responses at most,
and it avoids depending on how the database stores the JSON."""
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import curriculum_data
from .models import CurriculumSurveyResponse
from .views import _data_ctx, administrator_required

PAGE_SIZE = 25
DATA_SETS = [("real", "Real answers"), ("dummy", "Dummy (test) answers"), ("all", "Both")]


def _summary(resp, names_by_code):
    data = resp.data if isinstance(resp.data, dict) else {}
    info = data.get("personal_info") if isinstance(data.get("personal_info"), dict) else {}
    user = resp.user
    subjects = []
    for subj in data.get("subjects") or []:
        if not isinstance(subj, dict):
            continue
        code = str(subj.get("code") or "")
        skills = []
        for sk in subj.get("skills") or []:
            if isinstance(sk, dict) and sk.get("name"):
                skills.append({"name": str(sk["name"]), "level": str(sk.get("level") or "")})
            elif isinstance(sk, str):
                skills.append({"name": sk, "level": ""})
        subjects.append({"code": code, "name": str(subj.get("name") or names_by_code.get(code, "")),
                         "term": str(subj.get("term_label") or subj.get("term") or ""), "skills": skills})
    name = str(info.get("name") or (user.get_full_name() if user else "") or "")
    email = str(info.get("ue_email") or (user.email if user else "") or "")
    year = info.get("year_level") or info.get("year_graduated") or ""
    return {
        "obj": resp,
        "name": name,
        "email": email,
        "student_number": str(info.get("student_number") or ""),
        "course": str(info.get("course") or ""),
        "year": f"Year {year}" if info.get("year_level") else (f"Graduated {year}" if year else ""),
        "account": user.email if user else "",
        "subjects": subjects,
        "skill_count": sum(len(s["skills"]) for s in subjects),
    }


def _search_text(row):
    parts = [row["name"], row["email"], row["student_number"], row["course"], row["account"],
             row["obj"].get_respondent_type_display(), str(row["obj"].pk)]
    for s in row["subjects"]:
        parts += [s["code"], s["name"]] + [k["name"] for k in s["skills"]]
    return " ".join(parts).lower()


@administrator_required
def survey_responses_view(request):
    q = request.GET.get("q", "").strip()
    rtype = request.GET.get("type", "")
    data_set = request.GET.get("set", "real")
    if data_set not in dict(DATA_SETS):
        data_set = "real"
    qs = CurriculumSurveyResponse.objects.select_related("user").order_by("-created_at", "-pk")
    if rtype in dict(CurriculumSurveyResponse.RESPONDENT_TYPES):
        qs = qs.filter(respondent_type=rtype)
    else:
        rtype = ""
    if data_set != "all":
        qs = qs.filter(is_dummy=(data_set == "dummy"))
    names_by_code = {code: info["name"] for code, info in curriculum_data.subject_by_code().items()}
    rows = [_summary(r, names_by_code) for r in qs]
    if q:
        words = q.lower().split()
        rows = [r for r in rows if all(w in _search_text(r) for w in words)]
    page = Paginator(rows, PAGE_SIZE).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "data_survey_responses.html", _data_ctx(
        request, "responses",
        page=page, total=len(rows), q=q, rtype=rtype, data_set=data_set,
        types=CurriculumSurveyResponse.RESPONDENT_TYPES, data_sets=DATA_SETS,
        query_string=params.urlencode(),
    ))


@administrator_required
@require_POST
def survey_responses_delete_view(request):
    ids = [i for i in request.POST.getlist("ids") if i.isdigit()]
    next_url = request.POST.get("next") or ""
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse("survey_responses")
    if not ids:
        messages.error(request, "Choose at least one survey response to delete.")
        return redirect(next_url)
    deleted, _ = CurriculumSurveyResponse.objects.filter(pk__in=ids).delete()
    messages.success(request, f"Deleted {deleted} survey response{'' if deleted == 1 else 's'}.")
    return redirect(next_url)
