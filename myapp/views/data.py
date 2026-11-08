from urllib.parse import urlencode


from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..pipeline import manager as pipeline
from .common import administrator_required


# ---------------------------------------------------------------------------
# Data  (View Data / Import Data / Data Extraction, plus Ghost Jobs for everyone else)
# View Data is open to every logged-in user. Import and Data Extraction change files on the
# server (and scraping / extraction make outbound requests and spend API quota), so they are
# Administrator-only.
# ---------------------------------------------------------------------------
def _data_ctx(request, tab, **extra):
    return {"active_page": "data", "data_tab": tab, **extra}


@login_required
def data_view(request):
    summary = pipeline.disk_summary()
    tables = []
    pipeline.ensure_skill_csvs()
    for key, (label, _fn) in pipeline.TABLES.items():
        if key in pipeline.SOURCES:
            info = summary["sources"][key]["compiled"]
        else:
            info = pipeline._file_info(pipeline.table_path(key))
        tables.append({"key": key, "label": label, "exists": info["exists"],
                       "delete_note": pipeline.DELETABLE_TABLES.get(key, "")})
    clear_sources = [{"key": s, "label": pipeline.SOURCE_LABELS[s]} for s in pipeline.SOURCES]
    default = next((t["key"] for t in tables if t["exists"]), tables[0]["key"])
    if request.GET.get("source") in pipeline.TABLES:
        default = request.GET["source"]
    return render(request, "data_view.html", _data_ctx(request, "view", tables=tables, default_table=default,
                                                       clear_sources=clear_sources))


@administrator_required
@require_POST
def data_delete_view(request, key):
    if key not in pipeline.TABLES:
        raise Http404
    label = pipeline.TABLES[key][0]
    error = pipeline.delete_table(key)
    if error:
        messages.error(request, error)
    else:
        messages.success(request, f"Deleted {label}.")
    return redirect(reverse("data") + "?" + urlencode({"source": key}))


@administrator_required
@require_POST
def data_clear_source_view(request, source):
    """Extracted Skills: remove every job posting from one source (Kalibrr, Trabajo or Foundit), keep the others'."""
    if source not in pipeline.SOURCES:
        raise Http404
    removed, error = pipeline.clear_extracted_source(source)
    if error:
        messages.error(request, error)
    else:
        messages.success(request, f"Cleared {removed} {pipeline.SOURCE_LABELS[source]} job posting(s) from "
                                  "Extracted Skills; Hard Skills and Soft Skills were rebuilt.")
    return redirect(reverse("data") + "?" + urlencode({"source": "extracted"}))


@login_required
def data_table_view(request):
    key = request.GET.get("source", "")
    if key not in pipeline.TABLES:
        return JsonResponse({"ok": False, "error": "Unknown data source."}, status=400)
    try:
        page = int(request.GET.get("page", 1))
        size = int(request.GET.get("page_size", 50))
        sort = int(request.GET["sort"]) if request.GET.get("sort", "") != "" else None
        # per-column filters arrive as f<column index>=text
        filters = {int(k[1:]): v for k, v in request.GET.items() if k[:1] == "f" and k[1:].isdigit() and v.strip()}
    except ValueError:
        return JsonResponse({"ok": False, "error": "Bad paging values."}, status=400)
    try:
        data = pipeline.query_table(key, request.GET.get("q", ""), page, size, sort=sort,
                                    desc=request.GET.get("dir") == "desc", filters=filters)
    except (OSError, UnicodeDecodeError) as exc:
        return JsonResponse({"ok": False, "error": f"Couldn't read that file: {exc}"}, status=500)
    return JsonResponse({"ok": True, **data})


@login_required
def data_download_view(request, key):
    if key not in pipeline.TABLES:
        raise Http404
    path = pipeline.table_path(key)
    if not path.is_file():
        raise Http404("That file doesn't exist yet.")
    return FileResponse(open(path, "rb"), as_attachment=True, filename=path.name, content_type="text/csv")


@administrator_required
def data_import_view(request):
    if request.method == "POST":
        kind = request.POST.get("import_type", "")
        files = request.FILES.getlist("files")
        if kind not in pipeline.IMPORT_TYPES:
            messages.error(request, "Choose what you are importing.")
            return redirect("data_import")
        if not files:
            messages.error(request, "Choose at least one file to import.")
            return redirect("data_import")
        label, fmt, target = pipeline.IMPORT_TYPES[kind]

        if fmt == "json":
            res = pipeline.import_json_files(target, files, overwrite=request.POST.get("mode") == "replace")
            for err in res["errors"]:
                messages.error(request, err)
            if res["added"] or res["existing"]:
                msg = f"{label}: {res['added']} file(s) added to data/jsons/{target}/"
                if res["existing"]:
                    msg += f", {res['existing']} already existed (skipped)"
                if res["invalid"]:
                    msg += f", {res['invalid']} didn't look like {pipeline.SOURCE_LABELS[target]} job files (ignored)"
                messages.success(request, msg + ".")
                if res["added"] and request.POST.get("compile_after") == "on":
                    ok, last = pipeline.compile_now(target)
                    if ok:
                        messages.success(request, f"Rebuilt data/compiled_{target}.csv from the JSON files.")
                    else:
                        messages.error(request, f"Imported, but compiling failed: {last}")
            elif not res["errors"]:
                messages.error(request, f"None of those files looked like {pipeline.SOURCE_LABELS[target]} job JSONs.")
        else:
            if len(files) > 1:
                messages.error(request, "Import one CSV at a time.")
                return redirect("data_import")
            try:
                res = pipeline.import_csv(target, files[0], merge=request.POST.get("mode") != "replace")
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    f"{label}: {res['added']} row(s) added, {res['skipped']} skipped (duplicate or missing job_id); "
                    + (f"{res['merged']} repeated posting(s) merged; " if res.get("merged") else "")
                    + f"{res['total']} row(s) now in {pipeline.table_path(target).name}.")
        return redirect("data_import")

    return render(request, "data_import.html", _data_ctx(
        request, "import", summary=pipeline.disk_summary(), import_types=pipeline.IMPORT_TYPES))


@administrator_required
def failed_saves_download_view(request, name):
    """One failed saves log (data/failed_saves/), as a download."""
    path = pipeline.failed_saves_path(name)
    if path is None:
        raise Http404("That log doesn't exist.")
    return FileResponse(open(path, "rb"), as_attachment=True, filename=path.name, content_type="text/csv")


@administrator_required
@require_POST
def failed_saves_delete_view(request):
    """Delete one failed saves log (the page asks to confirm first)."""
    name = request.POST.get("name", "")
    error = pipeline.delete_failed_saves(name)
    if _wants_json(request):
        left = pipeline.list_failed_saves()
        return JsonResponse({"ok": error is None, "error": error, "count": len(left),
                             "latest": left[0]["when"] if left else ""}, status=200 if error is None else 400)
    if error:
        messages.error(request, error)
    else:
        messages.success(request, f"Deleted {name}.")
    return redirect(reverse("data_extraction") + "#scrape")


def _extraction_ctx(request, form=None, ghost_form=None, auto_form=None, errors=None):
    """Data Extraction: Scrape Data, Skill Extraction, Ghost Job Detection, What to run and
    Automation, on one page."""
    from .. import automation, ghost_jobs
    from ..pipeline import search_terms

    form = form or pipeline.get_extraction_settings()
    extra = form.get("extra_searches") or []
    skipped = form.get("skipped_searches") or []
    off = {t.lower() for t in skipped}
    locked = [{**s, "on": s["term"].lower() not in off} for s in search_terms.default_searches()]
    pipeline.ensure_skill_csvs()
    found = ghost_jobs.detect()
    flagged = ghost_jobs.flagged_postings()
    auto = automation.status()
    failed_saves = pipeline.list_failed_saves()
    return _data_ctx(
        request, "extraction",
        form=form,
        extra_text="\n".join(extra),
        locked_searches=locked,
        ched_ticked=sum(1 for s in locked if s["on"]),
        multiple_count=len(search_terms.multiple_list(extra, skipped)),
        job_sources=[{"key": s.key, "label": s.label, "site": s.site} for s in pipeline.SOURCE_REGISTRY],
        run=pipeline.get_run_state(),
        summary=pipeline.disk_summary(),
        keys_text=pipeline.read_api_keys_text(),
        key_count=pipeline.count_api_keys(),
        max_batch=pipeline.MAX_BATCH_SIZE,
        default_model=pipeline.DEFAULT_MODEL,
        ghost=ghost_form or ghost_jobs.get_settings(),
        flagged=flagged, ghost_total=len(found or {}), ghost_has_data=found is not None,
        ghost_excluded=sum(1 for r in flagged if r["excluded"]),
        max_chars=ghost_jobs.MAX_DESCRIPTION_CHARS,
        failed_saves=failed_saves,
        auto=auto,
        auto_form=auto_form or auto["settings"],
        weekdays=list(enumerate(automation.WEEKDAYS)),
        max_every_days=automation.MAX_EVERY_DAYS,
        errors=errors or {},
    )


def _save_extraction_sections(post) -> dict:
    """Saves each part of the Data Extraction form that is valid: the pipeline settings
    (Scrape Data, Skill Extraction, What to run), Ghost Job Detection and Automation are
    checked and saved separately, so a mistake in one never throws away the others.
    Returns {"run" | "ghost" | "auto": error message} for the parts that weren't saved."""
    from .. import automation, ghost_jobs

    form, error = pipeline.parse_extraction_form(post, for_run=False)
    ghost_form, ghost_error = ghost_jobs.parse_settings_form(post)
    auto_form, auto_error = automation.parse_form(post)
    if not auto_error and auto_form["enabled"]:
        sources = form["sources"] if not error else pipeline.get_scrape_settings()["sources"]
        if not sources:
            auto_error = "Automation: tick at least one job source under Scrape Data before turning it on."
    if not error:
        pipeline.save_extraction_settings(form)
    if not ghost_error:
        ghost_jobs.save_settings(ghost_form)
    if not auto_error:
        automation.save_settings(auto_form)
    return {k: v for k, v in (("run", error), ("ghost", ghost_error), ("auto", auto_error)) if v}


def _wants_json(request):
    return request.headers.get("X-Requested-With") == "fetch"


@administrator_required
def data_extraction_view(request):
    """GET shows the page. Every change on it is saved automatically: the page posts the whole
    form with action=autosave and gets JSON back (what was saved, what wasn't and why, and the
    refreshed summaries). action=run saves too, then starts the ticked steps and opens the
    Console. action=save is the no-JavaScript fallback (and what Enter does)."""
    from django.template.loader import render_to_string
    from .. import automation

    if request.method != "POST":
        return render(request, "data_extraction.html", _extraction_ctx(request))

    action = request.POST.get("action")
    errors = _save_extraction_sections(request.POST)

    if action == "autosave" or (action == "save" and _wants_json(request)):
        ctx = _extraction_ctx(request)
        auto = ctx["auto"]
        cfg = ctx["form"]
        return JsonResponse({
            "ok": not errors,
            "errors": errors,
            "meta": {
                "skills": f"{cfg['model']} · {cfg['batch_size']} rows per prompt · {ctx['key_count']} API key"
                          + ("" if ctx["key_count"] == 1 else "s"),
                "ghost": (f"{len(ctx['flagged'])} of {ctx['ghost_total']} posting"
                          + ("" if ctx["ghost_total"] == 1 else "s") + " marked")
                         if ctx["ghost_has_data"] else "No extracted postings yet",
                "auto_on": auto["settings"]["enabled"],
                "auto": auto["describe"],
            },
            "ghost_html": render_to_string("_dx_ghost_marked.html", ctx, request=request),
            "auto_html": render_to_string("_dx_auto_status.html", ctx, request=request),
        }, status=200)

    # Plain form posts always end in a redirect, so refreshing the page never asks to resend it.
    for msg in errors.values():
        messages.error(request, msg)
    if action != "run":
        if not errors:
            messages.success(request, "Data Extraction settings saved.")
        return redirect("data_extraction")
    if "run" in errors:
        return redirect("data_extraction")
    run_cfg = pipeline.get_extraction_settings()
    choice_error = pipeline.check_run_choices(run_cfg)
    if choice_error:
        messages.error(request, choice_error)
        return redirect("data_extraction")
    start_error = pipeline.start_run(pipeline.run_config(run_cfg), kind="extraction")
    if start_error:      # a problem with the run itself goes in the Console, not on the form
        pipeline.log_to_console(start_error)
    return redirect("console")


@administrator_required
def data_scrape_view(request):
    """Old Scrape Data / Extract Skills addresses: both are sections of Data Extraction now."""
    return redirect(reverse("data_extraction") + "#scrape")


@administrator_required
def data_extract_view(request):
    return redirect(reverse("data_extraction") + "#skills")


def _stop_and_redirect(request, target):
    # The outcome is written to the run log, so it shows in the Console either way.
    pipeline.stop_run()
    return redirect("console")


@administrator_required
def console_view(request):
    """Live status and log of the scrape / extract run (Administrator only)."""
    return render(request, "console.html", {"active_page": "console", "run": pipeline.get_run_state()})


@administrator_required
@require_POST
def console_stop_view(request):
    return _stop_and_redirect(request, "console")


@administrator_required
def scrape_status_view(request):
    st = pipeline.get_run_state()
    return JsonResponse({
        "status": st.get("status", "idle"),
        "kind": st.get("kind"),
        "current": st.get("current"),
        "steps": st.get("steps", []),
        "source": st.get("source"),
        "started_at": st.get("started_at"),
        "finished_at": st.get("finished_at"),
        "error": st.get("error"),
        "log": pipeline.read_log_tail(),
        "summary": pipeline.disk_summary(),
        "failed_saves": _last_failed_saves(st),
    })


def _last_failed_saves(st):
    """The finished run's failed saves log, for the Console: {"name", "url"}, {"name": ""} when
    every posting was saved, or None (still running, or the run didn't scrape)."""
    if st.get("status") == "running" or not st.get("failed_saves_stamp"):
        return None
    name = pipeline.last_failed_saves_report()
    if name is None:
        return None
    return {"name": name, "url": reverse("failed_saves_download", args=[name]) if name else ""}


@administrator_required
@require_POST
def api_keys_save_view(request):
    error = pipeline.save_api_keys_text(request.POST.get("keys", ""))
    if _wants_json(request):       # saved automatically from Data Extraction
        n = pipeline.count_api_keys()
        return JsonResponse({"ok": not error, "error": error, "count": n})
    if error:
        messages.error(request, error)
    else:
        n = pipeline.count_api_keys()
        messages.success(request, f"api_keys.txt saved ({n} key{'s' if n != 1 else ''}).")
    return redirect(reverse("data_extraction") + "#skills")


# ---------------------------------------------------------------------------
# Ghost Jobs: the detection settings (Administrators) and the postings they mark (everyone)
# ---------------------------------------------------------------------------
@login_required
def data_ghost_jobs_view(request):
    from .. import ghost_jobs

    form, error = ghost_jobs.get_settings(), None
    if request.method == "POST":
        if not request.user.is_administrator:
            raise PermissionDenied
        form, error = ghost_jobs.parse_settings_form(request.POST)
        if error:
            messages.error(request, error)
        else:
            ghost_jobs.save_settings(form)
            messages.success(request, "Ghost job settings saved. The marked postings below are updated.")
            return redirect(reverse("data_extraction") + "#ghost")
    elif request.user.is_administrator:
        # Administrators change the settings and see the marked postings on Data Extraction.
        return redirect(reverse("data_extraction") + "#ghost")
    pipeline.ensure_skill_csvs()
    found = ghost_jobs.detect()
    flagged = ghost_jobs.flagged_postings()
    return render(request, "data_ghost_jobs.html", _data_ctx(
        request, "ghost", form=form, flagged=flagged, total=len(found or {}), has_data=found is not None,
        excluded_count=sum(1 for r in flagged if r["excluded"]),
        max_chars=ghost_jobs.MAX_DESCRIPTION_CHARS, can_edit=request.user.is_administrator,
        form_error=error))
