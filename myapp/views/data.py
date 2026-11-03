from urllib.parse import urlencode


from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..pipeline import manager as pipeline
from .common import administrator_required


# ---------------------------------------------------------------------------
# Data  (four separate pages: View Data / Import Data / Scrape Data / Extract Skills)
# View Data is open to every logged-in user. Import, Scrape and Extract Skills change files on the
# server (and Scrape spends API quota / makes outbound requests), so they are
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
    """Extracted Skills: remove every Kalibrr (or Trabajo) job posting, keep the other source's."""
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


def _scrape_ctx(request, form=None):
    return _data_ctx(
        request, "scrape",
        form=form or pipeline.get_scrape_settings(),
        run=pipeline.get_run_state(),
        summary=pipeline.disk_summary(),
    )


def _extract_ctx(request, form=None):
    summary = pipeline.disk_summary()
    return _data_ctx(
        request, "extract",
        form=form or pipeline.get_extract_settings(),
        run=pipeline.get_run_state(),
        summary=summary,
        keys_text=pipeline.read_api_keys_text(),
        key_count=pipeline.count_api_keys(),
        max_batch=pipeline.MAX_BATCH_SIZE,
        default_model=pipeline.DEFAULT_MODEL,
    )


@administrator_required
def data_scrape_view(request):
    return render(request, "data_scrape.html", _scrape_ctx(request))


@administrator_required
@require_POST
def scrape_run_view(request):
    cfg, error = pipeline.parse_scrape_form(request.POST)
    if not error:
        start_error = pipeline.start_run(cfg, kind="scrape")
        if start_error:      # a problem with the run itself goes in the Console, not on the form
            pipeline.log_to_console(start_error)
            return redirect("console")
    if error:
        messages.error(request, error)
        return render(request, "data_scrape.html", _scrape_ctx(request, form=cfg))
    pipeline.save_scrape_settings(cfg)
    return redirect("console")


@administrator_required
def data_extract_view(request):
    return render(request, "data_extract.html", _extract_ctx(request))


@administrator_required
@require_POST
def extract_run_view(request):
    cfg, error = pipeline.parse_extract_form(request.POST)
    if not error:
        start_error = pipeline.start_run(cfg, kind="extract")
        if start_error:
            pipeline.log_to_console(start_error)
            return redirect("console")
    if error:
        messages.error(request, error)
        return render(request, "data_extract.html", _extract_ctx(request, form=cfg))
    pipeline.save_extract_settings(cfg)
    return redirect("console")


def _stop_and_redirect(request, target):
    # The outcome is written to the run log, so it shows in the Console either way.
    pipeline.stop_run()
    return redirect("console")


@administrator_required
@require_POST
def scrape_stop_view(request):
    return _stop_and_redirect(request, "data_scrape")


@administrator_required
@require_POST
def extract_stop_view(request):
    return _stop_and_redirect(request, "data_extract")


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
    })


@administrator_required
@require_POST
def api_keys_save_view(request):
    error = pipeline.save_api_keys_text(request.POST.get("keys", ""))
    if error:
        messages.error(request, error)
    else:
        n = pipeline.count_api_keys()
        messages.success(request, f"api_keys.txt saved ({n} key{'s' if n != 1 else ''}).")
    return redirect("data_extract")
