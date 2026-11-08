"""
UEnvision — Job Market page: how the job postings in data/extracted_skills.csv change
over time (posting volume per quarter, rising and falling skills, roles, employers,
locations, work setup, pay and entry-level vs senior skills).

The page is live: it reads extracted_skills.csv on every request (cached until the file
changes), so postings added by a scrape + Extract Skills run or by Import Data show up the
next time the page loads or refreshes itself.

Skills are counted the same way as everywhere else in UEnvision (job_roles.postings):
the hard_skills column as written in the data set, once per posting. Nothing is merged
into other names, so a skill's count here is what counting hard_skills.csv gives.

Unlike the Dashboard, this page also counts non-tech postings (isTechJob = False) in the
volume chart, employers, cities, work setup and pay, because the change in mix is part
of the story. Every skill number (top skills, rising / falling, entry vs senior) uses
tech postings only, the same postings the homepage, Dashboard and hard_skills.csv count.

The Dashboard's "Exclude possible ghost jobs" switch applies here too (ghost_jobs.EXCLUDE).
"""
import statistics

from . import ghost_jobs
from . import job_roles
from .pipeline import manager as pipeline
from .pipeline.skills_schema import split_skills

DEFAULT_SOURCE = "kalibrr"
DEFAULT_SINCE = 2024
TOP_SKILLS = 15
SHIFT_SKILLS = 8          # rising and falling skills shown each
SHIFT_MIN_POSTS = 25      # a skill needs this many tech postings to be in the rising / falling chart
TOP_EMPLOYERS = 10
TOP_CITIES = 8
TOP_LEVEL_SKILLS = 10
ENTRY_LEVELS = ("Entry", "Junior")
SENIOR_LEVELS = ("Senior", "Lead/Manager")
LEVEL_ORDER = ("Entry", "Junior", "Mid", "Senior", "Lead/Manager")
WORK_MODES = ("On-site", "Hybrid", "Work from home", "Remote")

_CACHE = {"stamp": None, "rows": None, "results": {}}


def _money(value):
    try:
        v = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _rows():
    """-> list of one dict per posting with the fields this page needs, or None when
    there's no extracted data yet. Cached until extracted_skills.csv changes."""
    from . import gap_analysis

    path = pipeline.extracted_csv()
    try:
        st = path.stat()
    except OSError:
        return None
    stamp = (st.st_mtime_ns, st.st_size)
    if _CACHE["stamp"] == stamp:
        return _CACHE["rows"]
    loaded = pipeline.load_table("extracted")
    if loaded is None:
        return None
    columns, raw = loaded
    idx = {c: i for i, c in enumerate(columns)}

    def get(r, c):
        i = idx.get(c)
        return r[i].strip() if i is not None and i < len(r) else ""

    rows = []
    for r in raw:
        m = job_roles._month_of(get, r)
        if not m:
            continue  # undated postings can't be placed on the timeline
        hard = {}
        for name in split_skills(get(r, "hard_skills")):
            hit = gap_analysis._standardize(name)
            if hit:
                hard.setdefault(hit[0], hit[1])
        tech_flag = job_roles._flag(get(r, "isTechJob"))
        role = job_roles.role_for(get(r, "job_name"), get(r, "function"), is_tech=bool(tech_flag))
        lo, hi = _money(get(r, "base_salary")), _money(get(r, "maximum_salary"))
        monthly = None
        if lo and get(r, "salary_currency").upper() == "PHP" and get(r, "salary_interval").lower() == "month":
            monthly = (lo + (hi or lo)) / 2
        rows.append({
            "source": get(r, "source").lower(),
            "ghost_key": (get(r, "source"), get(r, "job_id")),
            "year": int(m.group(1)),
            "month": int(m.group(2)),
            "tech": tech_flag if tech_flag is not None else bool(role),
            "role": role,
            "company": get(r, "company_name"),
            "city": get(r, "city"),
            "work_mode": get(r, "work_mode"),
            "level": get(r, "experience_level"),
            "fresh_grads": job_roles._flag(get(r, "open_to_fresh_grads")),
            "monthly_pay": monthly,
            "hard": hard,
        })
    _CACHE.update(stamp=stamp, rows=rows, results={})
    return rows


def sources_available():
    """-> [(key, label)] for the sources that have postings, in the registry's order."""
    rows = _rows() or []
    present = {r["source"] for r in rows}
    return [(k, pipeline.SOURCE_LABELS.get(k, k.capitalize())) for k in pipeline.SOURCES if k in present]


def years_available():
    return sorted({r["year"] for r in (_rows() or [])})


def _tally(postings):
    """-> (counts {key: n}, label {key: display}) — a skill once per posting."""
    counts, label = {}, {}
    for p in postings:
        for k, disp in p["hard"].items():
            counts[k] = counts.get(k, 0) + 1
            label.setdefault(k, disp)
    return counts, label


def _ranked(counts, label, n):
    return sorted(counts, key=lambda k: (-counts[k], label[k].lower()))[:n]


def _pct(part, whole):
    return round(part / whole * 100, 1) if whole else 0.0


def compute(source=DEFAULT_SOURCE, since=DEFAULT_SINCE):
    """Everything the Job Market page draws, for one source ("" = all) from `since`
    (a year) to the newest posting. -> dict with "exists": False when there's no data."""
    rows = _rows()
    if rows is None:
        return {"exists": False}
    exclude_ghosts = ghost_jobs.EXCLUDE.get()
    found = (ghost_jobs.detect() or {}) if exclude_ghosts else {}
    # The ghost job marks change when their settings or the data change, so they're part of the key.
    key = (source, since, exclude_ghosts, ghost_jobs._stamp() if exclude_ghosts else None)
    if key in _CACHE["results"]:
        return _CACHE["results"][key]

    chosen = [r for r in rows if (not source or r["source"] == source) and r["year"] >= since]
    ghosts_hidden = 0
    if exclude_ghosts:
        kept = [r for r in chosen if found.get(r["ghost_key"], {}).get("keep_when_excluding", True)]
        ghosts_hidden = len(chosen) - len(kept)
        chosen = kept
    updated = pipeline.skills_data_updated()
    result = {
        "exists": True,
        "source": source,
        "source_label": pipeline.SOURCE_LABELS.get(source, "All sources") if source else "All sources",
        "since": since,
        "updated": updated.isoformat() if updated else None,
        "total": len(chosen),
        "ghosts_excluded": exclude_ghosts,
        "ghosts_hidden": ghosts_hidden,
    }
    if not chosen:
        result["empty"] = True
        _CACHE["results"][key] = result
        return result

    tech = [r for r in chosen if r["tech"]]
    years = sorted({r["year"] for r in chosen})
    last = max((r["year"], r["month"]) for r in chosen)
    first = min((r["year"], r["month"]) for r in chosen)
    result.update({
        "tech_total": len(tech),
        "companies": len({r["company"] for r in chosen if r["company"]}),
        "first_month": f"{first[0]:04d}-{first[1]:02d}",
        "last_month": f"{last[0]:04d}-{last[1]:02d}",
        "years": years,
    })

    # Posting volume per quarter, tech vs non-tech. The newest quarter is marked partial.
    quarters = {}
    for r in chosen:
        q = (r["year"], (r["month"] - 1) // 3 + 1)
        slot = quarters.setdefault(q, {"tech": 0, "nontech": 0})
        slot["tech" if r["tech"] else "nontech"] += 1
    last_q = (last[0], (last[1] - 1) // 3 + 1)
    qkeys = []
    y, q = min(quarters)
    while (y, q) <= last_q:
        qkeys.append((y, q))
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    result["quarters"] = [{"label": f"Q{q} {y}", "tech": quarters.get((y, q), {}).get("tech", 0),
                           "nontech": quarters.get((y, q), {}).get("nontech", 0),
                           "partial": (y, q) == last_q and last[1] % 3 != 0}
                          for y, q in qkeys]

    # Top skills across the tech postings (as on the Dashboard and in hard_skills.csv),
    # with each year's count.
    counts, label = _tally(tech)
    by_year = {y: _tally([r for r in tech if r["year"] == y])[0] for y in years}
    result["top_skills"] = [{"skill": label[k], "count": counts[k], "pct": _pct(counts[k], len(tech)),
                             "by_year": [by_year[y].get(k, 0) for y in years]}
                            for k in _ranked(counts, label, TOP_SKILLS)]
    result["unique_skills"] = len(counts)

    # Rising / falling: share of tech postings in the first vs the latest year.
    tech_years = sorted({r["year"] for r in tech})
    result["shift"] = None
    if len(tech_years) >= 2:
        y0, y1 = tech_years[0], tech_years[-1]
        t0 = [r for r in tech if r["year"] == y0]
        t1 = [r for r in tech if r["year"] == y1]
        c_all, lab = _tally(tech)
        c0, c1 = _tally(t0)[0], _tally(t1)[0]
        floor = min(SHIFT_MIN_POSTS, max(2, len(tech) // 50))  # 25 on a full data set, lower on a small one
        moves = []
        for k, n in c_all.items():
            if n < floor:
                continue
            s0, s1 = _pct(c0.get(k, 0), len(t0)), _pct(c1.get(k, 0), len(t1))
            moves.append({"skill": lab[k], "from": s0, "to": s1, "change": round(s1 - s0, 1)})
        rising = sorted([m for m in moves if m["change"] > 0], key=lambda m: -m["change"])[:SHIFT_SKILLS]
        falling = sorted([m for m in moves if m["change"] < 0], key=lambda m: m["change"])[:SHIFT_SKILLS]
        result["shift"] = {"from_year": y0, "to_year": y1, "from_posts": len(t0), "to_posts": len(t1),
                           "min_posts": floor, "rising": rising, "falling": falling[::-1]}

    # Roles (the same job role groups as the student dashboard), share of tech postings per year.
    role_rows = []
    tech_by_year = {y: [r for r in tech if r["year"] == y] for y in tech_years}
    for rkey, rlabel, _ in job_roles.ROLES + [(None, "Other tech roles", None)]:
        n = sum(1 for r in tech if r["role"] == rkey)
        if n:
            role_rows.append({"role": rlabel, "count": n,
                              "by_year": [_pct(sum(1 for r in tech_by_year[y] if r["role"] == rkey),
                                               len(tech_by_year[y])) for y in tech_years]})
    role_rows.sort(key=lambda x: (x["role"] == "Other tech roles", -x["count"]))
    result["roles"] = {"years": tech_years, "rows": role_rows}

    # Employers and locations.
    def top_of(field, n):
        tally = {}
        for r in chosen:
            if r[field]:
                tally[r[field]] = tally.get(r[field], 0) + 1
        top = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0].lower()))[:n]
        return [{"name": name, "count": c, "pct": _pct(c, len(chosen))} for name, c in top]

    result["employers"] = top_of("company", TOP_EMPLOYERS)
    result["employers_share"] = _pct(sum(e["count"] for e in result["employers"]), len(chosen))
    result["cities"] = top_of("city", TOP_CITIES)

    # Work setup per year (share of postings).
    modes = [m for m in WORK_MODES if any(r["work_mode"] == m for r in chosen)]
    result["work_modes"] = {"years": years, "rows": [
        {"mode": m, "by_year": [_pct(sum(1 for r in chosen if r["year"] == y and r["work_mode"] == m),
                                     sum(1 for r in chosen if r["year"] == y)) for y in years]}
        for m in modes]}

    # Pay by experience level: median of each posting's PHP monthly range midpoint.
    pay = []
    for lvl in LEVEL_ORDER:
        vals = [r["monthly_pay"] for r in chosen if r["level"] == lvl and r["monthly_pay"]]
        if vals:
            pay.append({"level": lvl, "postings": sum(1 for r in chosen if r["level"] == lvl),
                        "priced": len(vals), "median": round(statistics.median(vals))})
    result["pay"] = pay
    result["priced"] = sum(1 for r in chosen if r["monthly_pay"])

    # Entry-level vs senior skills (tech postings).
    entry = [r for r in tech if r["level"] in ENTRY_LEVELS or r["fresh_grads"]]
    senior = [r for r in tech if r["level"] in SENIOR_LEVELS]

    def level_top(group):
        c, lab = _tally(group)
        return [{"skill": lab[k], "count": c[k]} for k in _ranked(c, lab, TOP_LEVEL_SKILLS)]

    result["entry"] = {"postings": len(entry), "skills": level_top(entry)}
    result["senior"] = {"postings": len(senior), "skills": level_top(senior)}
    result["fresh_grads"] = [{"year": y, "pct": _pct(sum(1 for r in chosen if r["year"] == y and r["fresh_grads"]),
                                                     sum(1 for r in chosen if r["year"] == y))} for y in years]

    _CACHE["results"][key] = result
    return result
