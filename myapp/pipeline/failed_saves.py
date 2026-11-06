"""
Failed saves log: the job postings a scrape found but couldn't save, one CSV per run.

While a run scrapes, each scraper writes what happens to every job posting it tries
(saved or failed, and why) into the run's work folder (--report-dir), one file per source:
    data/.state/failed_saves_run/<source>_events.csv
When the run ends, build_report() turns those into one downloadable CSV in data/failed_saves/:
    kalibrr_S120_F3_trabajo_S80_F5_2026-11-06_2130.csv
S = postings saved, F = postings that failed to save, for each source that had a failed save
(a source with none is left out of the name and the file). No failed saves, no file.
The date and time (Philippine time) at the end keep each run's file separate.

Stdlib only: the scrapers import it as a plain script next to them.
"""
import csv
import os
import re
from datetime import datetime, timezone
from pathlib import Path

EVENT_FIELDS = ["status", "source", "search", "job_id", "title", "company", "url", "reason", "time"]
REPORT_FIELDS = ["source", "search", "job_id", "title", "company", "url", "reason", "failed_at"]
NAME_RE = re.compile(r"^(?:[a-z0-9]+_S\d+_F\d+_)+\d{4}-\d{2}-\d{2}_\d{4}(?:-\d+)?\.csv$")
DONE_MARK = "report_done.txt"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Recorder:
    """What one scraper (one search of one source) did with each job posting.
    With no report_dir it records nothing, so the scrapers still work on their own."""

    def __init__(self, report_dir, source, search):
        self.path = Path(report_dir) / f"{source}_events.csv" if report_dir else None
        self.source, self.search = source, search

    def _write(self, status, job_id="", title="", company="", url="", reason=""):
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            new = not self.path.exists()
            with open(self.path, "a", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(EVENT_FIELDS)
                w.writerow([status, self.source, self.search, job_id or "", title or "", company or "",
                            url or "", reason or "", _now()])
        except OSError:
            pass    # the log must never stop a scrape

    def saved(self, job_id="", title="", company="", url=""):
        self._write("saved", job_id, title, company, url)

    def failed(self, reason, job_id="", title="", company="", url=""):
        self._write("failed", job_id, title, company, url, reason)


def _read_events(report_dir: Path):
    """-> {source: {"saved": n, "failed": [rows]}} in the order the sources appear in `order`."""
    out = {}
    for path in sorted(Path(report_dir).glob("*_events.csv")):
        try:
            with open(path, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    src = row.get("source") or path.name[:-len("_events.csv")]
                    rec = out.setdefault(src, {"saved": 0, "failed": []})
                    if row.get("status") == "saved":
                        rec["saved"] += 1
                    elif row.get("status") == "failed":
                        rec["failed"].append(row)
        except (OSError, csv.Error):
            continue
    return out


def build_report(report_dir, out_dir, stamp, order=()):
    """Write the run's failed saves CSV. Returns its path, or None when nothing failed.
    Runs once per run: a second call (the run was stopped after it ended) does nothing."""
    report_dir, out_dir = Path(report_dir), Path(out_dir)
    mark = report_dir / DONE_MARK
    if mark.exists() or not report_dir.is_dir():
        return None
    events = _read_events(report_dir)
    sources = [s for s in order if s in events] + sorted(s for s in events if s not in order)
    failing = [s for s in sources if events[s]["failed"]]
    path = None
    if failing:
        name = "_".join(f"{s}_S{events[s]['saved']}_F{len(events[s]['failed'])}" for s in failing)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{name}_{stamp}.csv"
        n = 1
        while path.exists():
            n += 1
            path = out_dir / f"{name}_{stamp}-{n}.csv"
        tmp = path.with_suffix(".csv.tmp")
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:     # -sig: Excel reads it as UTF-8
            w = csv.writer(f)
            w.writerow(REPORT_FIELDS)
            for s in failing:
                for r in events[s]["failed"]:
                    w.writerow([s, r.get("search", ""), r.get("job_id", ""), r.get("title", ""),
                                r.get("company", ""), r.get("url", ""), r.get("reason", ""), r.get("time", "")])
        os.replace(tmp, path)
    mark.write_text(path.name if path else "", encoding="utf-8")
    return path


def report_of(report_dir):
    """The file name build_report() wrote for this run ("" when nothing failed), or None
    when the report hasn't been built yet."""
    try:
        return (Path(report_dir) / DONE_MARK).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def list_reports(out_dir, limit=None):
    """[{name, sources: [(source, saved, failed)], when, size, failed}] the latest run first."""
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return []
    rows = []
    for p in out_dir.iterdir():
        if not (p.is_file() and NAME_RE.match(p.name)):
            continue
        parts = re.findall(r"([a-z0-9]+)_S(\d+)_F(\d+)", p.name)
        stat = p.stat()
        rows.append({"name": p.name, "sources": [(s, int(a), int(b)) for s, a, b in parts],
                     "when": _when(p.name),
                     "mtime": stat.st_mtime, "size": stat.st_size,
                     "failed": sum(int(b) for _, _, b in parts)})
    rows.sort(key=lambda r: (_sort_key(r["name"]), r["mtime"]), reverse=True)     # the latest run first
    return rows[:limit] if limit else rows


def _sort_key(name):
    """("2026-11-06", "2130", 2) for ..._2026-11-06_2130-2.csv: the run's time, then the same-minute count."""
    m = re.search(r"_(\d{4}-\d{2}-\d{2})_(\d{4})(?:-(\d+))?\.csv$", name)
    return (m.group(1), m.group(2), int(m.group(3) or 1)) if m else ("", "", 0)


def _when(name):
    """The run's date and time from the file name: "Nov 6, 2026 · 9:30 PM"."""
    m = re.search(r"_(\d{4}-\d{2}-\d{2})_(\d{4})(?:-\d+)?\.csv$", name)
    try:
        t = datetime.strptime(m.group(1) + m.group(2), "%Y-%m-%d%H%M")
    except (AttributeError, ValueError):
        return ""
    return t.strftime("%b %d, %Y · %I:%M %p").replace(" 0", " ")


def safe_report_path(out_dir, name):
    """The report file for a download link, or None for anything that isn't one."""
    if not NAME_RE.match(name or ""):
        return None
    p = Path(out_dir) / name
    return p if p.is_file() else None


def main(argv=None):
    """python failed_saves.py <report_dir> <out_dir> <stamp> [source ...]  (run at the end of a run)"""
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 3:
        print("usage: failed_saves.py REPORT_DIR OUT_DIR STAMP [SOURCE ...]")
        return 2
    path = build_report(args[0], args[1], args[2], order=args[3:])
    if path:
        print(f"Failed saves log: {path.name} (download it from Data Extraction > Scrape Data or the Console).")
    else:
        print("Failed saves log: every job posting found was saved; no file this time.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
