from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render

from .. import feedback_nudge
from .. import job_market


def _params(request):
    """-> (sources, since) from the query string. sources: the ticked source tick boxes
    (repeated ?source=, or one comma-separated value), defaulting to the scraped job boards
    (Kalibrr, Trabajo, Foundit) from 2024. Imported datasets such as Djinni are only counted
    when ticked. "all" (old links) = the job boards. Raises ValueError for anything unknown."""
    picked = []
    for value in request.GET.getlist("source"):
        picked += [s.strip().lower() for s in value.split(",") if s.strip()]
    known = {s["key"] for s in job_market.sources_available()} | set(job_market.DEFAULT_SOURCES)
    if picked == ["all"] or not picked:
        picked = job_market.default_sources()
    elif any(s not in known for s in picked):
        raise ValueError("Unknown source.")
    since = int(request.GET.get("since", job_market.DEFAULT_SINCE))
    if not 2000 <= since <= 2100:
        raise ValueError("Bad year.")
    return picked, since


@login_required
def job_market_view(request):
    """Job Market page (faculty and administrators; students/alumni are kept out by
    LearnerAccessMiddleware). The charts are drawn by job-market.js from job_market_data_view."""
    feedback_nudge.record_use(request.user)
    try:
        sources, since = _params(request)
    except ValueError:
        sources, since = job_market.default_sources(), job_market.DEFAULT_SINCE
    years = job_market.years_available()
    available = job_market.sources_available()
    return render(request, "job_market.html", {
        "active_page": "job_market",
        "sources": available,
        "has_datasets": any(s["dataset"] for s in available),
        "years": years[::-1],
        "picked": sources,
        "since": since,
    })


@login_required
def job_market_data_view(request):
    """JSON for the Job Market page. Read from data/extracted_skills.csv on each request
    (cached until the file changes), so new postings appear without a deploy."""
    try:
        sources, since = _params(request)
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    try:
        data = job_market.compute(sources, since)
    except (OSError, UnicodeDecodeError) as exc:
        return JsonResponse({"ok": False, "error": f"Couldn't read the data: {exc}"}, status=500)
    return JsonResponse({"ok": True, **data})
