"""
UEnvision — possible ghost job detection.

A "ghost job" is a posting that looks like it isn't a real, open position. Postings are
only MARKED here: nothing is removed from data/extracted_skills.csv, hard_skills.csv or
any other file, and every result counts every posting unless the person viewing it has
switched on "Exclude possible ghost jobs" (Dashboard filters). That switch is remembered
in their session and read by job_roles.it_postings(), so the homepage, Dashboard, skill
gap analysis and Recommendations all leave the same postings out.

Warning signs (each one can be turned on / off on Data -> Data Extraction -> Ghost Job Detection):

  * Same job posted twice: the same company and the same job title under a different
    job ID (also across Kalibrr and Trabajo). This sign alone marks a posting. When
    the exclude switch is on, the newest copy is kept so the job still counts once.
  * Weak signs, which only mark a posting when enough of them apply together
    (the "weak signs needed" setting, 2 by default):
      - salary hidden (Kalibrr's salary_shown is false, or no salary at all)
      - vague description (shorter than the minimum length, 500 characters by default;
        read from data/compiled_<source>.csv)
      - company not verified on the job board (Kalibrr only)

A sign that can't be checked for a posting (no compiled file to read the description
from, no "verified" field on Trabajo) never counts against it.

Only the scraped job boards (pipeline/sources.py: Kalibrr, Trabajo, Foundit) are checked and
listed. Imported public datasets (Import Data, e.g. Djinni) are left out, the same way
job_roles.source_filter() keeps them off the Dashboard and every other result.
"""
import contextvars
import json
import re

from .pipeline import manager as pipeline

DEFAULT_SETTINGS = {
    "flag_duplicates": True,
    "flag_hidden_salary": True,
    "flag_unverified": True,
    "min_description_chars": 500,    # 0 = don't check the description
    "weak_signs_needed": 2,          # 1 or 2
}
MAX_DESCRIPTION_CHARS = 5000

# Session key for the "Exclude possible ghost jobs" switch.
SESSION_KEY = "exclude_ghost_jobs"
# Set per request by middleware.GhostJobsMiddleware from the session; it_postings() reads it.
EXCLUDE = contextvars.ContextVar("exclude_ghost_jobs", default=False)

_CACHE = {"key": None, "value": None}
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


# ---------------------------------------------------------------------------
# Settings (data/.state/ghost_settings.json, like the scrape / extract settings)
# ---------------------------------------------------------------------------
def settings_file():
    return pipeline.state_dir() / "ghost_settings.json"


def get_settings() -> dict:
    cfg = dict(DEFAULT_SETTINGS)
    try:
        saved = json.loads(settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    if isinstance(saved, dict):
        for k, default in DEFAULT_SETTINGS.items():
            v = saved.get(k)
            if isinstance(default, bool) and isinstance(v, bool):
                cfg[k] = v
            elif isinstance(default, int) and not isinstance(default, bool) and isinstance(v, int) and not isinstance(v, bool):
                cfg[k] = v
    cfg["min_description_chars"] = max(0, min(cfg["min_description_chars"], MAX_DESCRIPTION_CHARS))
    cfg["weak_signs_needed"] = 1 if cfg["weak_signs_needed"] == 1 else 2
    return cfg


def parse_settings_form(post) -> tuple[dict, str | None]:
    cfg = {
        "flag_duplicates": post.get("flag_duplicates") == "on",
        "flag_hidden_salary": post.get("flag_hidden_salary") == "on",
        "flag_unverified": post.get("flag_unverified") == "on",
    }
    raw = str(post.get("min_description_chars", "")).strip() or "0"
    try:
        cfg["min_description_chars"] = int(raw)
    except ValueError:
        return cfg, "Minimum description length must be a whole number of characters."
    if not 0 <= cfg["min_description_chars"] <= MAX_DESCRIPTION_CHARS:
        return cfg, f"Minimum description length must be between 0 and {MAX_DESCRIPTION_CHARS} characters."
    try:
        cfg["weak_signs_needed"] = int(post.get("weak_signs_needed", 2))
    except ValueError:
        cfg["weak_signs_needed"] = 0
    if cfg["weak_signs_needed"] not in (1, 2):
        return cfg, "Weak signs needed must be 1 or 2."
    return cfg, None


def save_settings(cfg: dict) -> None:
    pipeline.ensure_dirs()
    keep = {k: cfg[k] for k in DEFAULT_SETTINGS if k in cfg}
    pipeline._atomic_write_text(settings_file(), json.dumps(keep, indent=2))
    _CACHE.update(key=None, value=None)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------
def _norm(text) -> str:
    return " ".join(_NON_ALNUM.sub(" ", str(text or "").lower()).split())


def title_key(title) -> str:
    """Case, spacing and punctuation don't make it a different job ("Data Engineer {Python, SQL}"
    and "Data Engineer [Python , SQL]" are the same title); any other word does."""
    return _norm(title)


def _bool(value):
    v = str(value or "").strip().lower()
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no"):
        return False
    return None


def _has_number(value) -> bool:
    try:
        return float(str(value).strip()) > 0
    except (TypeError, ValueError):
        return False


def _description_lengths() -> dict:
    """{(source, job_id): description length} from data/compiled_<source>.csv.
    A source without a compiled file just has no entries (the sign isn't checked)."""
    out = {}
    for source in pipeline.SOURCES:
        loaded = pipeline.load_table(source)
        if loaded is None:
            continue
        columns, rows = loaded
        if "job_id" not in columns or "description" not in columns:
            continue
        i_id, i_desc = columns.index("job_id"), columns.index("description")
        for r in rows:
            if i_id < len(r):
                desc = r[i_desc] if i_desc < len(r) else ""
                out[(source, r[i_id].strip())] = len(desc.strip())
    return out


def _stamp():
    parts = [get_settings_stamp()]
    for key in ("extracted", *pipeline.SOURCES):
        try:
            st = pipeline.table_path(key).stat()
            parts.append((key, st.st_mtime_ns, st.st_size))
        except OSError:
            parts.append((key, None))
    return tuple(parts)


def get_settings_stamp():
    try:
        st = settings_file().stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _checked_source(source) -> bool:
    """A scraped job board ("" = rows saved before there was a source column). Imported
    datasets such as Djinni are not checked, like job_roles.source_filter()."""
    return source.lower() in {*pipeline.SOURCES, ""}


def _rows():
    """Every extracted job board posting as a dict of the columns detection needs
    (imported datasets are skipped, see _checked_source)."""
    loaded = pipeline.load_table("extracted")
    if loaded is None:
        return None
    columns, rows = loaded
    idx = {c: i for i, c in enumerate(columns)}

    def get(r, c):
        i = idx.get(c)
        return r[i].strip() if i is not None and i < len(r) else ""

    out = []
    for r in rows:
        if not _checked_source(get(r, "source")):
            continue
        date = next((get(r, c) for c in ("date", "created_at", "date_posted", "activation_date") if get(r, c)), "")
        out.append({
            "source": get(r, "source"), "job_id": get(r, "job_id"),
            "job_name": get(r, "job_name"), "company_name": get(r, "company_name"),
            "job_url": get(r, "job_url"), "date": date,
            "salary_shown": _bool(get(r, "salary_shown")),
            "has_salary": _has_number(get(r, "base_salary")) or _has_number(get(r, "maximum_salary")),
            "company_verified": _bool(get(r, "company_verified")),
        })
    return out


def _id_order(job_id):
    try:
        return (0, int(job_id))
    except ValueError:
        return (1, job_id)


def detect(cfg: dict | None = None):
    """-> {(source, job_id): {"reasons": [...], "flagged": bool, "keep_when_excluding": bool,
    "duplicate_of": [...]}} for every extracted posting, or None when there's no data yet.
    Cached until the data files or the settings change."""
    use_cache = cfg is None
    if use_cache:
        stamp = _stamp()
        if _CACHE["key"] == stamp:
            return _CACHE["value"]
        cfg = get_settings()
    rows = _rows()
    if rows is None:
        return None
    lengths = _description_lengths() if cfg["min_description_chars"] else {}

    # Same company + same title, different job ID.
    groups = {}
    if cfg["flag_duplicates"]:
        from .pipeline.dedupe_trabajo import company_key
        for row in rows:
            ck, tk = company_key(row["company_name"]), title_key(row["job_name"])
            if ck and tk:
                groups.setdefault((ck, tk), []).append(row)

    result = {}
    for row in rows:
        result[(row["source"], row["job_id"])] = {"reasons": [], "weak": 0, "duplicate_of": [],
                                                  "duplicate": False, "newest_copy": False}
    for members in groups.values():
        ids = {(m["source"], m["job_id"]) for m in members}
        if len(ids) < 2:
            continue
        newest = max(members, key=lambda m: (m["date"], _id_order(m["job_id"])))
        for m in members:
            info = result[(m["source"], m["job_id"])]
            info["duplicate"] = True
            info["newest_copy"] = m is newest
            info["duplicate_of"] = sorted({f"{o['source']} #{o['job_id']}" for o in members
                                           if (o["source"], o["job_id"]) != (m["source"], m["job_id"])})
            info["reasons"].append("Same job also posted as " + ", ".join(info["duplicate_of"]))

    for row in rows:
        info = result[(row["source"], row["job_id"])]
        if cfg["flag_hidden_salary"] and (row["salary_shown"] is False
                                          or (row["salary_shown"] is None and not row["has_salary"])):
            info["weak"] += 1
            info["reasons"].append("Salary hidden")
        n = lengths.get((row["source"], row["job_id"]))
        if cfg["min_description_chars"] and n is not None and n < cfg["min_description_chars"]:
            info["weak"] += 1
            info["reasons"].append(f"Short description ({n} characters)")
        if cfg["flag_unverified"] and row["company_verified"] is False:
            info["weak"] += 1
            info["reasons"].append("Company not verified")

    for info in result.values():
        weak_flag = info["weak"] >= cfg["weak_signs_needed"]
        info["flagged"] = info["duplicate"] or weak_flag
        # Excluding keeps one copy of a duplicated job, unless the weak signs mark it too.
        info["keep_when_excluding"] = not weak_flag and (not info["duplicate"] or info["newest_copy"])
        if not info["flagged"]:
            info["reasons"] = []
    if use_cache:
        _CACHE.update(key=stamp, value=result)
    return result


def is_flagged(source, job_id) -> bool:
    found = (detect() or {}).get((source, str(job_id)))
    return bool(found and found["flagged"])


def flagged_postings():
    """Marked postings for the Data -> Ghost Jobs page, newest first."""
    found = detect()
    rows = _rows()
    if found is None or rows is None:
        return []
    out = []
    for row in rows:
        info = found[(row["source"], row["job_id"])]
        if info["flagged"]:
            out.append({**row, "reasons": info["reasons"], "excluded": not info["keep_when_excluding"]})
    out.sort(key=lambda r: (r["company_name"].lower(), title_key(r["job_name"]), r["date"]))
    return out
