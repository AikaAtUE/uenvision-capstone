"""
Backend helpers for the Data pages (View / Import / Scrape / Extract Skills).

Disk layout (all under settings.DATA_DIR):

    data/jsons/kalibrr/            one JSON per scraped Kalibrr job
    data/jsons/trabajo/            one JSON per scraped Trabajo job
    data/compiled_kalibrr.csv      compiled from the Kalibrr JSONs
    data/compiled_trabajo.csv      compiled from the Trabajo JSONs
    data/extracted_skills.csv      Gemini skill extraction output
    data/.state/                   run state, run log, remembered form values, resume file

The scrapers / compiler / extractor in this package are the original command-line
scripts; this module only builds their command lines and runs them
(through orchestrator.py) so the web UI never imports their sys.exit()-style code.
"""
import csv
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

from .skills_schema import (SKILL_CSVS, UNIVERSAL_COLUMNS, normalize_record,
                            write_skill_csvs)

PIPELINE_DIR = Path(__file__).resolve().parent
SOURCES = ("kalibrr", "trabajo")
SOURCE_LABELS = {"kalibrr": "Kalibrr", "trabajo": "Trabajo"}

# What the View Data dropdown can show: key -> (label, csv filename)
TABLES = {
    "kalibrr": ("Raw Job Data — Kalibrr", "compiled_kalibrr.csv"),
    "trabajo": ("Raw Job Data — Trabajo", "compiled_trabajo.csv"),
    "extracted": ("Extracted Skills", "extracted_skills.csv"),
    "custom_skills": ("Custom Skills (not in the ontology)", "ontology/custom_skills.csv"),
    "hard_skills": ("Hard Skills", SKILL_CSVS["hard_skills"]),
    "soft_skills": ("Soft Skills", SKILL_CSVS["soft_skills"]),
}

DEFAULT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_BATCH_SIZE = 20
MAX_BATCH_SIZE = 100         # same cap the extraction script enforces
HEARTBEAT_STALE_SECONDS = 60
MAX_JSON_BYTES = 10 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 500 * 1024 * 1024
MAX_ZIP_MEMBERS = 50000
MAX_CSV_BYTES = 300 * 1024 * 1024
MAX_KEYS_FILE_BYTES = 50 * 1024
CELL_PREVIEW_CHARS = 300

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
def data_dir() -> Path:
    return Path(settings.DATA_DIR)


def json_dir(source: str) -> Path:
    return data_dir() / "jsons" / source


def compiled_csv(source: str) -> Path:
    return data_dir() / f"compiled_{source}.csv"


def extracted_csv() -> Path:
    return data_dir() / "extracted_skills.csv"


def ontology_dir() -> Path:
    return data_dir() / "ontology"


def state_dir() -> Path:
    return data_dir() / ".state"


def api_keys_path() -> Path:
    return Path(settings.API_KEYS_FILE)


def ensure_dirs() -> None:
    for s in SOURCES:
        json_dir(s).mkdir(parents=True, exist_ok=True)
    state_dir().mkdir(parents=True, exist_ok=True)


def table_path(key: str) -> Path:
    return data_dir() / TABLES[key][1]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write_text(path: Path, text: str, encoding="utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(text)
        for attempt in range(100):     # Windows: "Access is denied" while another process has the file open
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 99:
                    raise
                time.sleep(0.05)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ---------------------------------------------------------------------------
# What is on disk
# ---------------------------------------------------------------------------
def _file_info(path: Path) -> dict:
    if not path.is_file():
        return {"exists": False}
    st = path.stat()
    return {
        "exists": True,
        "size": st.st_size,
        "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
    }


def count_json(source: str) -> int:
    d = json_dir(source)
    if not d.is_dir():
        return 0
    with os.scandir(d) as it:
        return sum(1 for e in it if e.is_file() and e.name.endswith(".json"))


def disk_summary() -> dict:
    out = {"sources": {}, "extracted": _file_info(extracted_csv())}
    for s in SOURCES:
        out["sources"][s] = {
            "label": SOURCE_LABELS[s],
            "json_count": count_json(s),
            "compiled": _file_info(compiled_csv(s)),
        }
    return out


# ---------------------------------------------------------------------------
# Reading CSVs for View Data (cached by mtime+size)
# ---------------------------------------------------------------------------
_table_cache: dict = {}


def load_table(key: str):
    """-> (columns, rows) or None when the file doesn't exist yet."""
    path = table_path(key)
    if not path.is_file():
        return None
    st = path.stat()
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _table_cache.get(key)
    if hit and hit[0] == stamp:
        return hit[1], hit[2]
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        columns = next(reader, [])
        rows = [r for r in reader if r]
    _table_cache[key] = (stamp, columns, rows)
    return columns, rows


def query_table(key: str, q: str = "", page: int = 1, page_size: int = 50) -> dict:
    loaded = load_table(key)
    if loaded is None:
        return {"exists": False, "columns": [], "rows": [], "total": 0, "matched": 0, "page": 1, "pages": 1}
    columns, rows = loaded
    q = (q or "").strip().lower()
    if q:
        rows = [r for r in rows if any(q in c.lower() for c in r)]
    matched = len(rows)
    page_size = max(1, min(page_size, 200))
    pages = max(1, -(-matched // page_size))
    page = max(1, min(page, pages))
    chunk = rows[(page - 1) * page_size: page * page_size]

    def cell(v: str):
        return v if len(v) <= CELL_PREVIEW_CHARS else v[:CELL_PREVIEW_CHARS] + "…"

    return {
        "exists": True,
        "columns": columns,
        "rows": [[cell(c) for c in r] + [""] * (len(columns) - len(r)) for r in chunk],
        "total": len(loaded[1]),
        "matched": matched,
        "page": page,
        "pages": pages,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# Hard / soft skills CSVs and the dashboard numbers
# ---------------------------------------------------------------------------
def ensure_skill_csvs() -> None:
    """(Re)build hard_skills.csv / soft_skills.csv from extracted_skills.csv when missing or stale."""
    src = extracted_csv()
    if not src.is_file():
        return
    stamp = src.stat().st_mtime
    if all(table_path(k).is_file() and table_path(k).stat().st_mtime >= stamp for k in SKILL_CSVS):
        return
    loaded = load_table("extracted")
    if loaded is None:
        return
    columns, rows = loaded
    recs = [dict(zip(columns, r)) for r in rows]
    write_skill_csvs(recs, str(data_dir()))
    for k in SKILL_CSVS:
        _table_cache.pop(k, None)


_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})")


def _month_range(first: str, last: str) -> list[str]:
    y, m = int(first[:4]), int(first[5:])
    ly, lm = int(last[:4]), int(last[5:])
    out = []
    while (y, m) <= (ly, lm):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def skills_dashboard(kind: str = "hard", top: int = 10, source: str = "", level: str = "",
                     months: int = 0) -> dict:
    """Numbers behind the dashboard charts.

    kind: 'hard' | 'soft'. top: how many skills. source / level: optional filters.
    months: 0 = every month with data, otherwise only the latest N months.
    A skill is counted once per job posting that mentions it. Postings and skill
    names come from job_roles.it_postings() -- the same IT/CS postings and
    standardized names the homepage, student dashboard and gap analysis use."""
    from .. import gap_analysis, job_roles

    kind = "soft" if kind == "soft" else "hard"
    top = max(1, min(int(top), 30))
    everything = job_roles.it_postings()
    if everything is None:
        return {"exists": False}
    sources = sorted({p["source"] for p in everything if p["source"]})
    levels = sorted({p["level"] for p in everything if p["level"]})
    jobs = [(p["month"], p[kind]) for p in job_roles.it_postings(source, level)]

    dated = sorted({m for m, _ in jobs if m})
    month_list = _month_range(dated[0], dated[-1]) if dated else []
    if months and len(month_list) > months:
        month_list = month_list[-months:]
    window = set(month_list)
    in_window = [(m, s) for m, s in jobs if (m in window)] if month_list else []

    def tally(items):
        return gap_analysis._tally(sk for _, sk in items)

    counts, label = tally(jobs)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], label[kv[0]].lower()))
    total_jobs = len(jobs)
    bars = [{"skill": label[k], "count": c, "pct": round(c / total_jobs * 100, 1) if total_jobs else 0}
            for k, c in ranked[:top]]

    w_counts, w_label = tally(in_window)
    w_ranked = sorted(w_counts.items(), key=lambda kv: (-kv[1], w_label[kv[0]].lower()))[:top]
    per_month = {m: 0 for m in month_list}
    series = {k: {m: 0 for m in month_list} for k, _ in w_ranked}
    for m, sk in in_window:
        per_month[m] += 1
        for k in sk:
            if k in series:
                series[k][m] += 1
    return {
        "exists": True,
        "kind": kind,
        "updated": _file_info(extracted_csv()).get("modified"),
        "sources": sources,
        "levels": levels + (["Not specified"] if any(not p["level"] for p in everything) else []),
        "stats": {
            "postings": total_jobs,
            "unique_skills": len(counts),
            "top_skill": bars[0]["skill"] if bars else None,
            "top_skill_pct": bars[0]["pct"] if bars else 0,
            "undated": sum(1 for m, _ in jobs if not m),
        },
        "bars": bars,
        "months": month_list,
        "postings_per_month": [per_month[m] for m in month_list],
        "series": [{"skill": w_label[k], "counts": [series[k][m] for m in month_list]} for k, _ in w_ranked],
    }


# ---------------------------------------------------------------------------
# api_keys.txt
# ---------------------------------------------------------------------------
def read_api_keys_text() -> str:
    p = api_keys_path()
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def env_api_keys() -> list[str]:
    """Extra keys from the GEMINI_API_KEYS environment variable (comma- or
    newline-separated). Empty when it isn't set, which is the usual local case."""
    raw = os.environ.get(getattr(settings, "GEMINI_API_KEYS_ENV", "GEMINI_API_KEYS"), "")
    return [k.strip() for k in raw.replace(",", "\n").splitlines() if k.strip()]


def count_api_keys(text: str | None = None) -> int:
    if text is None:
        keys = [ln.strip() for ln in read_api_keys_text().splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
        return len(dict.fromkeys(keys + env_api_keys()))
    return sum(1 for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#"))


def save_api_keys_text(text: str) -> str | None:
    """Returns an error string or None."""
    if len(text.encode("utf-8")) > MAX_KEYS_FILE_BYTES:
        return "That's too large for an API key list."
    lines = [ln.strip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    body = "\n".join(lines) + ("\n" if lines else "")
    p = api_keys_path()
    _atomic_write_text(p, body)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return None


# ---------------------------------------------------------------------------
# Remembered Scrape Data form values
# ---------------------------------------------------------------------------
DEFAULT_SCRAPE_SETTINGS = {
    "source": "trabajo",
    "keyword": "computer science",
    "delay_min": 1.5,
    "delay_max": 4.0,
    "max_jobs": "",
    "do_scrape": True,
    "do_compile": True,
}
DEFAULT_EXTRACT_SETTINGS = {
    "sources": list(SOURCES),
    "standardize": True,
    "batch_size": DEFAULT_BATCH_SIZE,
    "model": DEFAULT_MODEL,
}


def _settings_file() -> Path:
    return state_dir() / "scrape_settings.json"


def _extract_settings_file() -> Path:
    return state_dir() / "extract_settings.json"


def _load_saved(path: Path, cfg: dict) -> dict:
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            cfg.update({k: v for k, v in saved.items() if k in cfg})
    except (OSError, ValueError):
        pass
    return cfg


def get_scrape_settings() -> dict:
    return _load_saved(_settings_file(), dict(DEFAULT_SCRAPE_SETTINGS))


def get_extract_settings() -> dict:
    cfg = dict(DEFAULT_EXTRACT_SETTINGS)
    if not _extract_settings_file().is_file():
        # before Extract Skills had its own page these lived in the scrape settings file
        _load_saved(_settings_file(), cfg)
    return _load_saved(_extract_settings_file(), cfg)


_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{0,80}$")


def parse_scrape_form(post) -> tuple[dict, str | None]:
    """Validate the Scrape Data form. Returns (settings, error)."""
    cfg = dict(DEFAULT_SCRAPE_SETTINGS)
    cfg["source"] = post.get("source", "")
    cfg["keyword"] = " ".join(post.get("keyword", "").split())
    cfg["do_scrape"] = post.get("do_scrape") == "on"
    cfg["do_compile"] = post.get("do_compile") == "on"
    cfg["max_jobs"] = post.get("max_jobs", "").strip()

    if cfg["source"] not in SOURCES:
        return cfg, "Choose a data source (Trabajo or Kalibrr)."
    if not (cfg["do_scrape"] or cfg["do_compile"]):
        return cfg, "Tick at least one step to run."

    try:
        cfg["delay_min"] = float(post.get("delay_min", ""))
        cfg["delay_max"] = float(post.get("delay_max", ""))
    except ValueError:
        return cfg, "Minimum and maximum interval must be numbers (seconds)."
    if not (0 <= cfg["delay_min"] <= cfg["delay_max"] <= 600):
        return cfg, "Intervals must satisfy 0 ≤ minimum ≤ maximum ≤ 600 seconds."

    if cfg["max_jobs"]:
        if not cfg["max_jobs"].isdigit() or int(cfg["max_jobs"]) < 1:
            return cfg, "Max jobs must be a whole number of at least 1 (or left blank)."
        cfg["max_jobs"] = int(cfg["max_jobs"])

    if cfg["do_scrape"] and (not cfg["keyword"] or len(cfg["keyword"]) > 100):
        return cfg, "Enter a search keyword (up to 100 characters)."
    return cfg, None


def parse_extract_form(post) -> tuple[dict, str | None]:
    """Validate the Extract Skills form. Returns (settings, error).
    The "Standardize only" button (action=standardize) skips extraction."""
    cfg = dict(DEFAULT_EXTRACT_SETTINGS)
    standardize_only = post.get("action") == "standardize"
    picked = post.getlist("sources") if hasattr(post, "getlist") else list(post.get("sources", []))
    cfg["sources"] = [s for s in SOURCES if s in picked]
    cfg["model"] = post.get("model", "").strip()
    cfg["standardize"] = standardize_only or post.get("standardize") == "on"
    cfg["do_extract"] = not standardize_only
    cfg["do_standardize"] = cfg["standardize"]
    if cfg["do_extract"] and not cfg["sources"]:
        return cfg, "Tick at least one source to extract skills from (Kalibrr and/or Trabajo)."
    try:
        cfg["batch_size"] = int(post.get("batch_size", ""))
    except ValueError:
        return cfg, "Rows per prompt must be a whole number."
    if not 1 <= cfg["batch_size"] <= MAX_BATCH_SIZE:
        return cfg, f"Rows per prompt must be between 1 and {MAX_BATCH_SIZE}."
    if not _MODEL_RE.match(cfg["model"]):
        return cfg, "Enter a valid Gemini model name, e.g. " + DEFAULT_MODEL + "."
    return cfg, None


def save_scrape_settings(cfg: dict) -> None:
    ensure_dirs()
    keep = {k: v for k, v in cfg.items() if k in DEFAULT_SCRAPE_SETTINGS}
    _atomic_write_text(_settings_file(), json.dumps(keep, indent=2))


def save_extract_settings(cfg: dict) -> None:
    ensure_dirs()
    keep = {k: v for k, v in cfg.items() if k in DEFAULT_EXTRACT_SETTINGS}
    _atomic_write_text(_extract_settings_file(), json.dumps(keep, indent=2))


# ---------------------------------------------------------------------------
# Building the command lines
# ---------------------------------------------------------------------------

def build_steps(cfg: dict) -> list[dict]:
    py = sys.executable
    src = cfg.get("source") or (cfg.get("sources") or [""])[0]   # extraction runs have "sources", not "source"
    jd, csv_path = json_dir(src), compiled_csv(src)
    steps = []

    if cfg.get("do_scrape"):
        if src == "kalibrr":
            argv = [py, "-u", str(PIPELINE_DIR / "kalibrr_scraper.py"),
                    f"--text={cfg['keyword']}", f"--output-dir={jd}",
                    f"--delay-min={cfg['delay_min']}", f"--delay-max={cfg['delay_max']}"]
        else:
            argv = [py, "-u", str(PIPELINE_DIR / "trabajo_scraper.py"),
                    f"--keyword={cfg['keyword']}", f"--output-dir={jd}",
                    f"--delay-min={cfg['delay_min']}", f"--delay-max={cfg['delay_max']}"]
        if cfg["max_jobs"]:
            argv.append(f"--max-jobs={cfg['max_jobs']}")
        steps.append({"name": "scrape", "label": f"Scrape {SOURCE_LABELS[src]}", "argv": argv})

    if cfg.get("do_compile"):
        steps.append({"name": "compile", "label": f"Compile {SOURCE_LABELS[src]} JSONs to CSV",
                      "argv": [py, "-u", str(PIPELINE_DIR / "compile_jobs_to_csv.py"),
                               f"--source={src}", f"--input-dir={jd}", f"--output-csv={csv_path}"]})

    if cfg.get("do_extract"):
        # One step per ticked source; they all append to the same extracted_skills.csv / resume file.
        for ex_src in cfg.get("sources") or [src]:
            argv = [py, "-u", str(PIPELINE_DIR / "extract_skills_gemini.py"), str(compiled_csv(ex_src)),
                    f"--keys={api_keys_path()}", "--output=extracted_skills",
                    f"--output-dir={data_dir()}", f"--json-dir={state_dir()}",
                    f"--model={cfg['model']}", f"--batch-size={cfg['batch_size']}",
                    f"--source-label={ex_src}"]
            steps.append({"name": f"extract_{ex_src}", "label": f"Extract skills — {SOURCE_LABELS[ex_src]}",
                          "argv": argv})

    if cfg.get("do_standardize"):
        # After extraction: map the hard skills onto the ontology (exact -> fuzzy candidates -> Gemini).
        steps.append({"name": "standardize", "label": "Standardize hard skills", "argv": [
            py, "-u", str(PIPELINE_DIR / "standardize_skills_gemini.py"),
            f"--json={state_dir() / 'extracted_skills.json'}", f"--output-dir={data_dir()}",
            f"--ontology-dir={ontology_dir()}", f"--temp-csv={state_dir() / 'standardize_pending.csv'}",
            f"--keys={api_keys_path()}", f"--model={cfg['model']}", f"--batch-size={cfg['batch_size']}"]})
    return steps


# ---------------------------------------------------------------------------
# Run state (start / status / stop)
# ---------------------------------------------------------------------------
def _run_file() -> Path:
    return state_dir() / "run.json"


def _log_file() -> Path:
    return state_dir() / "run.log"


def _read_state() -> dict:
    for attempt in range(20):    # the run process may be swapping the file in right now (Windows)
        try:
            return json.loads(_run_file().read_text(encoding="utf-8"))
        except FileNotFoundError:
            break
        except (OSError, ValueError):
            time.sleep(0.05)
    return {"status": "idle"}


def _parse_ts(s):
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def get_run_state() -> dict:
    st = _read_state()
    if "kind" not in st:    # runs recorded before the Extract Skills page existed
        st["kind"] = "extract" if all(str(x.get("name", "")).startswith("extract") for x in st.get("steps", [])) and st.get("steps") else "scrape"
    if st.get("status") == "running":
        beat = _parse_ts(st.get("heartbeat") or st.get("started_at"))
        age = (datetime.now(timezone.utc) - beat).total_seconds() if beat else 1e9
        if age > HEARTBEAT_STALE_SECONDS:
            st["status"] = "interrupted"
            st["error"] = "The run stopped unexpectedly (server restarted or the process was killed). Run it again to resume."
    return st


def is_running() -> bool:
    return get_run_state().get("status") == "running"


def read_log_tail(max_bytes: int = 24000) -> str:
    p = _log_file()
    if not p.is_file():
        return ""
    with open(p, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        raw = f.read()
    text = raw.decode("utf-8", errors="replace")
    if size > max_bytes:
        text = text.split("\n", 1)[-1]
    # tqdm-style carriage returns: keep only the last update on each line
    return "\n".join(line.rsplit("\r", 1)[-1] for line in text.split("\n")).strip("\n")


def start_run(cfg: dict, kind: str = "scrape") -> str | None:
    """Launch the pipeline in a detached process. kind: 'scrape' (scrape + compile) or
    'extract' (skill extraction). Returns an error string or None."""
    ensure_dirs()
    if is_running():
        return "A run is already in progress. Wait for it to finish or stop it first."

    steps = build_steps(cfg)
    src = cfg.get("source") or (cfg.get("sources") or [""])[0]

    if cfg.get("do_extract"):
        if count_api_keys() == 0:
            return "Skill extraction needs at least one Gemini API key — add one in api_keys.txt below."
        for ex_src in cfg.get("sources") or []:
            if not compiled_csv(ex_src).is_file():
                return (f"There's no compiled {SOURCE_LABELS[ex_src]} CSV yet. Scrape and compile it on the "
                        f"Scrape Data page (or import a CSV) first — or untick {SOURCE_LABELS[ex_src]}.")
    if cfg.get("do_standardize"):
        if not (ontology_dir() / "mind_tech_ontology.csv").is_file():
            return "The ontology file is missing: put mind_tech_ontology.csv in data/ontology/."
        if not cfg.get("do_extract") and not (state_dir() / "extracted_skills.json").is_file():
            return "There are no extracted skills to standardize yet. Run Extract Skills first."
    if cfg.get("do_compile") and not cfg.get("do_scrape") and count_json(src) == 0:
        return f"There are no {SOURCE_LABELS[src]} job JSONs to compile yet. Tick “Scrape” (or import JSONs first)."

    # A stale resume file with no CSV would make the extractor think everything is already done.
    state_json = state_dir() / "extracted_skills.json"
    if cfg.get("do_extract") and state_json.is_file() and not extracted_csv().is_file():
        state_json.unlink()

    _log_file().write_text("", encoding="utf-8")
    log_to_console(f"Run started: {', '.join(x['label'] for x in steps)}. "
                   "It keeps going in the background, so you can leave this page.", "INFO")
    state = {
        "status": "running", "kind": kind,
        "source": (" + ".join(SOURCE_LABELS[x].lower() for x in cfg["sources"]) if cfg.get("do_extract")
                   else "standardize" if cfg.get("do_standardize") else src), "started_at": _now(), "heartbeat": _now(),
        "finished_at": None, "current": None, "pid": None, "error": None,
        "steps": [{"name": s["name"], "label": s["label"], "status": "pending"} for s in steps],
        "summary": {"keyword": cfg.get("keyword") if cfg.get("do_scrape") else None,
                    "delay_min": cfg.get("delay_min"), "delay_max": cfg.get("delay_max"),
                    "model": cfg.get("model") if cfg.get("do_extract") else None,
                    "batch_size": cfg.get("batch_size") if cfg.get("do_extract") else None},
    }
    _atomic_write_text(_run_file(), json.dumps(state, indent=2))
    run_cfg = {"state_file": str(_run_file()), "log_file": str(_log_file()),
               "cwd": str(settings.BASE_DIR), "steps": steps}
    cfg_path = state_dir() / "run_config.json"
    _atomic_write_text(cfg_path, json.dumps(run_cfg, indent=2))

    kwargs = {}
    if os.name == "nt":
        # CREATE_NO_WINDOW (not DETACHED_PROCESS): a detached process has no console, so every
        # step it started would pop open its own CMD window.
        kwargs["creationflags"] = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                                   | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(PIPELINE_DIR / "orchestrator.py"), str(cfg_path)],
            cwd=str(settings.BASE_DIR), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
    except OSError as exc:
        state.update(status="failed", error=f"Could not start the run: {exc}", finished_at=_now())
        _atomic_write_text(_run_file(), json.dumps(state, indent=2))
        return state["error"]
    # Only record the pid if the orchestrator hasn't already replaced the file.
    st = _read_state()
    if st.get("status") == "running" and not st.get("pid"):
        st["pid"] = proc.pid
        _atomic_write_text(_run_file(), json.dumps(st, indent=2))
    return None


def log_to_console(text: str, level: str = "ERROR") -> None:
    """Append a line to the run log so it shows up inside the Console's dark box."""
    try:
        ensure_dirs()
        stamp = datetime.now().strftime("%H:%M:%S")
        with open(_log_file(), "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {level}: {text}\n")
    except OSError:
        pass


def stop_run() -> bool:
    st = _read_state()
    if st.get("status") != "running" or not st.get("pid"):
        log_to_console("There's no run in progress to stop.", "INFO")
        return False
    pid = int(st["pid"])
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15)
        else:
            import signal
            os.killpg(pid, signal.SIGTERM)  # orchestrator + its running step share one process group
    except (OSError, subprocess.SubprocessError):
        pass
    st.update(status="stopped", current=None, finished_at=_now())
    for s in st.get("steps", []):
        if s["status"] in ("running", "pending"):
            s["status"] = "stopped" if s["status"] == "running" else "skipped"
    _atomic_write_text(_run_file(), json.dumps(st, indent=2))
    with open(_log_file(), "a", encoding="utf-8") as f:
        f.write("\n=== Stopped by user. Progress so far is saved; running again resumes where it left off. ===\n")
    return True


# ---------------------------------------------------------------------------
# Import Data
# ---------------------------------------------------------------------------
IMPORT_TYPES = {
    "json_kalibrr": ("Kalibrr job JSONs", "json", "kalibrr"),
    "json_trabajo": ("Trabajo job JSONs", "json", "trabajo"),
    "csv_kalibrr": ("Compiled Kalibrr CSV", "csv", "kalibrr"),
    "csv_trabajo": ("Compiled Trabajo CSV", "csv", "trabajo"),
    "csv_extracted": ("Extracted skills CSV", "csv", "extracted"),
}

_SAFE_RE = re.compile(r"[^A-Za-z0-9_-]+")
_TRABAJO_ID_RE = re.compile(r"^\d+-[A-Za-z0-9]{8,64}$")


def _json_target_name(source: str, data) -> str | None:
    """File name for an uploaded job JSON (same naming as the scrapers), or None if it isn't one."""
    if not isinstance(data, dict):
        return None
    if source == "kalibrr":
        job = (data.get("pageProps") or {}).get("job") if isinstance(data.get("pageProps"), dict) else None
        if not isinstance(job, dict) or not job.get("id") or not job.get("slug"):
            return None
        slug = _SAFE_RE.sub("-", str(job["slug"])).strip("-") or "job"
        return f"{_SAFE_RE.sub('-', str(job['id'])).strip('-')}_{slug}.json"
    jid = data.get("job_id")
    if not jid or not data.get("title"):
        return None
    jid = str(jid)
    return f"job-{jid}.json" if _TRABAJO_ID_RE.match(jid) else f"job-{_SAFE_RE.sub('-', jid).strip('-')}.json"


def import_json_files(source: str, uploads, overwrite: bool) -> dict:
    """Accepts .json files and/or .zip archives of them. Returns counts."""
    ensure_dirs()
    dest = json_dir(source)
    res = {"added": 0, "existing": 0, "invalid": 0, "errors": []}

    def handle(blob: bytes, label: str):
        try:
            data = json.loads(blob.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            res["invalid"] += 1
            return
        name = _json_target_name(source, data)
        if not name:
            res["invalid"] += 1
            return
        target = dest / name
        if target.exists() and not overwrite:
            res["existing"] += 1
            return
        _atomic_write_text(target, json.dumps(data, ensure_ascii=False, indent=2))
        res["added"] += 1

    for up in uploads:
        lower = up.name.lower()
        if lower.endswith(".zip"):
            try:
                zf = zipfile.ZipFile(up)
            except zipfile.BadZipFile:
                res["errors"].append(f"{up.name} is not a valid zip file.")
                continue
            with zf:
                infos = [i for i in zf.infolist()
                         if not i.is_dir() and i.filename.lower().endswith(".json")
                         and "__MACOSX" not in i.filename and not os.path.basename(i.filename).startswith(".")]
                if len(infos) > MAX_ZIP_MEMBERS or sum(i.file_size for i in infos) > MAX_ZIP_TOTAL_BYTES:
                    res["errors"].append(f"{up.name} is too large to import in one go.")
                    continue
                for info in infos:
                    if info.file_size > MAX_JSON_BYTES:
                        res["invalid"] += 1
                        continue
                    with zf.open(info) as fh:      # member names are never used as paths
                        handle(fh.read(MAX_JSON_BYTES + 1), info.filename)
        elif lower.endswith(".json"):
            if up.size > MAX_JSON_BYTES:
                res["invalid"] += 1
                continue
            handle(up.read(), up.name)
        else:
            res["errors"].append(f"{up.name}: only .json files or .zip archives of them are accepted.")
    return res


CSV_REQUIRED = {
    "kalibrr": {"job_id", "job_title", "description"},
    "trabajo": {"job_id", "job_title", "description"},
    "extracted": {"job_id", "hard_skills"},
}
_EXTRACTED_LIST_COLS = ("hard_skills", "hard_skills_raw", "soft_skills", "certifications_or_licenses")


def _read_csv_upload(upload):
    if upload.size > MAX_CSV_BYTES:
        raise ValueError("That CSV is too large.")
    try:
        text = io.TextIOWrapper(upload.file, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text)
        columns = list(reader.fieldnames or [])
        rows = [r for r in reader if any((v or "").strip() for v in r.values() if isinstance(v, str))]
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError(f"Couldn't read that file as a UTF-8 CSV ({exc}).")
    return columns, rows


def import_csv(kind: str, upload, merge: bool) -> dict:
    """kind: 'kalibrr' | 'trabajo' | 'extracted'. Returns counts."""
    ensure_dirs()
    columns, new_rows = _read_csv_upload(upload)
    if not columns:
        raise ValueError("That CSV has no header row.")
    missing = CSV_REQUIRED[kind] - set(columns)
    if missing:
        raise ValueError("Missing required column(s): " + ", ".join(sorted(missing)) + ".")
    if not new_rows:
        raise ValueError("That CSV has no data rows.")

    path = table_path(kind)
    existing_cols, existing_rows = [], []
    if merge and path.is_file():
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            rd = csv.DictReader(f)
            existing_cols = list(rd.fieldnames or [])
            existing_rows = list(rd)

    seen = {str(r.get("job_id", "")).strip() for r in existing_rows}
    added, skipped, to_add = 0, 0, []
    for r in new_rows:
        jid = str(r.get("job_id", "")).strip()
        if not jid:
            skipped += 1
            continue
        if jid in seen:
            skipped += 1
            continue
        seen.add(jid)
        to_add.append(r)
        added += 1

    if kind == "extracted":      # one universal layout for every source
        existing_rows = [normalize_record(r) for r in existing_rows]
        to_add = [normalize_record(r) for r in to_add]
        extra = []
        for r in existing_rows + to_add:
            extra += [c for c in r if c not in UNIVERSAL_COLUMNS and c not in extra]
        fieldnames = list(UNIVERSAL_COLUMNS) + extra
    else:
        fieldnames = existing_cols + [c for c in columns if c not in existing_cols]
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\r\n")
    w.writeheader()
    w.writerows(existing_rows + to_add)
    _atomic_write_text(path, buf.getvalue(), encoding="utf-8-sig")
    _table_cache.pop(kind, None)
    if kind == "extracted":
        ensure_skill_csvs()

    if kind == "extracted":
        _merge_extracted_state(existing_rows + to_add if merge else to_add, replace=not merge)
    return {"added": added, "skipped": skipped, "total": len(existing_rows) + added}


def _merge_extracted_state(rows: list, replace: bool) -> None:
    """Keep the extractor's resume file in step with imported rows, otherwise the next
    extraction run would regenerate the CSV without them (and re-extract them)."""
    state_file = state_dir() / "extracted_skills.json"
    state = []
    if not replace and state_file.is_file():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = []
    have = {str(r.get("job_id")) for r in state}
    for r in rows:
        if str(r.get("job_id", "")).strip() in have:
            continue
        rec = {k: (v if v != "" else None) for k, v in normalize_record(r).items()}
        for c in _EXTRACTED_LIST_COLS:
            v = r.get(c) or ""
            rec[c] = [x.strip() for x in v.split(";") if x.strip()]
        state.append(rec)
    _atomic_write_text(state_file, json.dumps(state, indent=2, ensure_ascii=False))


def compile_now(source: str) -> tuple[bool, str]:
    """Run the compile script synchronously (it's quick). Returns (ok, last log line)."""
    try:
        proc = subprocess.run(
            [sys.executable, "-u", str(PIPELINE_DIR / "compile_jobs_to_csv.py"),
             f"--source={source}", f"--input-dir={json_dir(source)}", f"--output-csv={compiled_csv(source)}"],
            capture_output=True, text=True, timeout=600, cwd=str(settings.BASE_DIR),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    _table_cache.pop(source, None)
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return proc.returncode == 0, (tail[-1] if tail else "")
