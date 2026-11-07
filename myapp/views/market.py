from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render

from .. import feedback_nudge
from .. import job_market


def _params(request):
    """-> (source, since) from the query string, defaulting to Kalibrr from 2024.
    source "all" = every source. Raises ValueError for anything else unknown."""
    source = request.GET.get("source", job_market.DEFAULT_SOURCE)
    source = "" if source == "all" else source
    if source and source not in dict(job_market.sources_available()):
        raise ValueError("Unknown source.")
    since = int(request.GET.get("since", job_market.DEFAULT_SINCE))
    if not 2000 <= since <= 2100:
        raise ValueError("Bad year.")
    return source, since


@login_required
def job_market_view(request):
    """Job Market page (faculty and administrators; students/alumni are kept out by
    LearnerAccessMiddleware). The charts are drawn by job-market.js from job_market_data_view."""
    feedback_nudge.record_use(request.user)
    try:
        source, since = _params(request)
    except ValueError:
        source, since = job_market.DEFAULT_SOURCE, job_market.DEFAULT_SINCE
    years = job_market.years_available()
    return render(request, "job_market.html", {
        "active_page": "job_market",
        "sources": job_market.sources_available(),
        "years": years[::-1],
        "source": source or "all",
        "since": since,
    })


@login_required
def job_market_data_view(request):
    """JSON for the Job Market page. Read from data/extracted_skills.csv on each request
    (cached until the file changes), so new postings appear without a deploy."""
    try:
        source, since = _params(request)
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    try:
        data = job_market.compute(source, since)
    except (OSError, UnicodeDecodeError) as exc:
        return JsonResponse({"ok": False, "error": f"Couldn't read the data: {exc}"}, status=500)
    return JsonResponse({"ok": True, **data})
