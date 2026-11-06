"""Data > Recommendations (administrators): the settings of the context-aware
recommendations (rec_context.py), the subject aliases the subject profiles use
(subject_profiles.py), and the background queue of skills waiting for Gemini (rec_queue.py)."""
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse

from .. import rec_queue, subject_profiles
from ..models import RecommendationJob, SubjectAlias, SubjectSkillStat
from .common import administrator_required


def _back():
    return redirect(reverse("rec_settings"))


@administrator_required
def rec_settings_view(request):
    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "settings":
            try:
                n = int(request.POST.get("min_respondents", ""))
            except ValueError:
                n = 0
            lo, hi = subject_profiles.MIN_RESPONDENTS_RANGE
            if not lo <= n <= hi:
                messages.error(request, f"Enter a number from {lo} to {hi}.")
            else:
                subject_profiles.save_settings({"min_respondents": n})
                messages.success(request, f"Saved. A skill now counts for a subject once {n} "
                                          f"{'person reports' if n == 1 else 'people report'} it there.")
        elif action == "alias_add":
            alias = " ".join(request.POST.get("alias", "").split())[:160]
            same = " ".join(request.POST.get("same_as", "").split())[:160]
            a_key, s_key = subject_profiles.name_key(alias), subject_profiles.name_key(same)
            if not a_key or not s_key:
                messages.error(request, "Pick both subject names.")
            elif a_key == s_key:
                messages.error(request, "Those are already the same name.")
            elif subject_profiles.alias_map().get(s_key) == a_key:
                messages.error(request, f"{same} is already set as the same subject as {alias}.")
            else:
                SubjectAlias.objects.update_or_create(alias_key=a_key, defaults={
                    "alias_name": alias, "same_as_key": s_key, "same_as_name": same, "created_by": request.user})
                subject_profiles.rebuild_all()
                messages.success(request, f"{alias} is now counted as the same subject as {same}.")
        elif action == "alias_delete":
            SubjectAlias.objects.filter(pk=request.POST.get("id")).delete()
            subject_profiles.rebuild_all()
            messages.success(request, "Removed. The two names are separate subjects again.")
        elif action == "retry":
            n = RecommendationJob.objects.filter(status=RecommendationJob.FAILED).update(
                status=RecommendationJob.PENDING, attempts=0, error="")
            rec_queue.start_background()
            messages.success(request, f"Queued {n} skill{'' if n == 1 else 's'} again.")
        elif action == "run":
            started = rec_queue.start_background()
            messages.success(request, "Started finding resources for the waiting skills." if started
                             else "It is already running.")
        elif action == "rebuild":
            n = subject_profiles.rebuild(False)
            subject_profiles.rebuild(True)
            messages.success(request, f"Rebuilt the subject profiles ({n} subject skills).")
        return _back()

    cfg = subject_profiles.get_settings()
    stats = SubjectSkillStat.objects.filter(is_dummy=False)
    return render(request, "rec_settings.html", {
        "active_page": "data", "data_tab": "recommendations",
        "cfg": cfg, "range": subject_profiles.MIN_RESPONDENTS_RANGE,
        "aliases": SubjectAlias.objects.all(),
        "subject_names": subject_profiles.subject_names(),
        "profile_subjects": stats.values("program", "subject_key").distinct().count(),
        "profile_rows": stats.count(),
        "counted_rows": sum(1 for p, l in stats.values_list("professors", "learners") if p + l >= cfg["min_respondents"]),
        "queue": rec_queue.status(),
    })
