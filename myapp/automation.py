"""
UEnvision — automatic Data Extraction runs.

When Automation is turned on (Data -> Data Extraction -> Automation), the whole pipeline
runs on a schedule with the saved settings of the sections above it: every job source
that is ticked, the MULTIPLE search list (the locked CHED roles plus the extra searches,
whatever the Single / Multiple switch says; that switch is for manual runs), and every
step: scrape, compile, extract skills, standardize hard skills, ghost job detection.

The schedule is checked by `python manage.py run_automation`, which the server runs every
5 minutes (deploy/uenvision-automation.timer). On a laptop nothing calls it unless you do:
`python manage.py run_automation --now` starts an automatic run right away.

Files (data/.state/):
    automation.json        the settings (on/off, how often, time of day)
    automation_state.json  next scheduled run, last run and result, last scheduler check

Times are Philippine time (UTC+8, no daylight saving); settings.AUTOMATION_UTC_OFFSET_HOURS
changes that.
"""
import json
from datetime import datetime, time as dtime, timedelta, timezone

from django.conf import settings

from .pipeline import manager as pipeline

FREQUENCIES = ("days", "weekdays")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MAX_EVERY_DAYS = 30
SCHEDULER_STALE_MINUTES = 15     # the timer checks every 5 minutes

DEFAULT_SETTINGS = {
    "enabled": False,
    "frequency": "days",     # "days": every N days; "weekdays": on the ticked days of the week
    "every_days": 1,
    "weekdays": [0],         # 0 = Monday
    "time": "02:00",         # HH:MM, Philippine time
}


def tz():
    hours = getattr(settings, "AUTOMATION_UTC_OFFSET_HOURS", 8)
    return timezone(timedelta(hours=hours), getattr(settings, "AUTOMATION_TIME_ZONE_LABEL", "PHT"))


def now():
    return datetime.now(tz())


def _settings_file():
    return pipeline.state_dir() / "automation.json"


def _state_file():
    return pipeline.state_dir() / "automation_state.json"


def _read(path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(path, data) -> None:
    pipeline.ensure_dirs()
    pipeline._atomic_write_text(path, json.dumps(data, indent=2))


def _parse_time(text):
    try:
        t = datetime.strptime(str(text).strip(), "%H:%M").time()
    except ValueError:
        return None
    return t


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def get_settings() -> dict:
    cfg = dict(DEFAULT_SETTINGS)
    saved = _read(_settings_file())
    if isinstance(saved.get("enabled"), bool):
        cfg["enabled"] = saved["enabled"]
    if saved.get("frequency") in FREQUENCIES:
        cfg["frequency"] = saved["frequency"]
    if isinstance(saved.get("every_days"), int) and 1 <= saved["every_days"] <= MAX_EVERY_DAYS:
        cfg["every_days"] = saved["every_days"]
    days = saved.get("weekdays")
    if isinstance(days, list) and days and all(isinstance(d, int) and 0 <= d <= 6 for d in days):
        cfg["weekdays"] = sorted(set(days))
    if _parse_time(saved.get("time", "")):
        cfg["time"] = saved["time"]
    return cfg


def parse_form(post) -> tuple[dict, str | None]:
    """The Automation section of the Data Extraction form. Returns (settings, error)."""
    cfg = dict(DEFAULT_SETTINGS)
    cfg["enabled"] = post.get("auto_enabled") == "on"
    cfg["frequency"] = post.get("auto_frequency", "days")
    raw_days = post.getlist("auto_weekdays") if hasattr(post, "getlist") else list(post.get("auto_weekdays", []))
    cfg["weekdays"] = sorted({int(d) for d in raw_days if str(d).isdigit() and 0 <= int(d) <= 6})
    cfg["time"] = str(post.get("auto_time", "")).strip()[:5]
    try:
        cfg["every_days"] = int(post.get("auto_every_days", ""))
    except ValueError:
        cfg["every_days"] = 0

    if cfg["frequency"] not in FREQUENCIES:
        return cfg, "Choose how often the automatic run happens."
    if not 1 <= cfg["every_days"] <= MAX_EVERY_DAYS:
        return cfg, f"Run every 1 to {MAX_EVERY_DAYS} days."
    if cfg["frequency"] == "weekdays" and not cfg["weekdays"]:
        return cfg, "Tick at least one day of the week for the automatic run."
    if not cfg["weekdays"]:
        cfg["weekdays"] = list(DEFAULT_SETTINGS["weekdays"])
    if not _parse_time(cfg["time"]):
        return cfg, "Enter the time of day for the automatic run (HH:MM)."
    return cfg, None


def save_settings(cfg: dict) -> None:
    """Saves the settings and, when they change the schedule, the next run time."""
    old = get_settings()
    keep = {k: cfg[k] for k in DEFAULT_SETTINGS}
    _write(_settings_file(), keep)
    state = get_state()
    schedule_keys = ("enabled", "frequency", "every_days", "weekdays", "time")
    if any(old[k] != keep[k] for k in schedule_keys) or not state.get("next_run"):
        state["next_run"] = first_run_after(keep, now()).isoformat() if keep["enabled"] else None
        _write(_state_file(), state)


def describe(cfg: dict) -> str:
    t = _parse_time(cfg["time"]) or dtime(2, 0)
    at = datetime.combine(datetime(2000, 1, 1), t).strftime("%I:%M %p").lstrip("0")
    if cfg["frequency"] == "weekdays":
        days = [WEEKDAYS[d] for d in cfg["weekdays"]]
        when = "every day" if len(days) == 7 else "every " + (", ".join(days[:-1]) + " and " + days[-1]
                                                              if len(days) > 1 else days[0])
    else:
        when = "every day" if cfg["every_days"] == 1 else f"every {cfg['every_days']} days"
    return f"{when} at {at}"


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------
def _at(day, cfg):
    return datetime.combine(day, _parse_time(cfg["time"]) or dtime(2, 0), tzinfo=tz())


def first_run_after(cfg: dict, moment: datetime) -> datetime:
    """The first scheduled time strictly after `moment`. For "every N days" the count starts
    from the first run (today's time if it's still ahead, otherwise tomorrow's)."""
    moment = moment.astimezone(tz())
    day = moment.date()
    if cfg["frequency"] == "weekdays":
        for add in range(8):
            d = day + timedelta(days=add)
            if d.weekday() in cfg["weekdays"] and _at(d, cfg) > moment:
                return _at(d, cfg)
    candidate = _at(day, cfg)
    return candidate if candidate > moment else _at(day + timedelta(days=1), cfg)


def following_run(cfg: dict, scheduled: datetime, moment: datetime) -> datetime:
    """The run after the one scheduled at `scheduled` (that started at `moment`).
    Runs missed while the server was off are not made up one by one."""
    if cfg["frequency"] == "weekdays":
        return first_run_after(cfg, max(scheduled, moment))
    nxt = _at(scheduled.astimezone(tz()).date() + timedelta(days=cfg["every_days"]), cfg)
    while nxt <= moment:
        nxt = _at(nxt.date() + timedelta(days=cfg["every_days"]), cfg)
    return nxt


def get_state() -> dict:
    return _read(_state_file())


def _parse(ts):
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def _fmt(moment, pattern):
    """Philippine time, whatever the server's time zone ("Mon, Nov 9, 2026 · 2:00 AM")."""
    if moment is None:
        return ""
    text = moment.astimezone(tz()).strftime(pattern)
    return text.replace(" 0", " ")


def _ago(moment):
    if moment is None:
        return ""
    minutes = int((now() - moment).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    return f"{hours // 24} days ago"


def status() -> dict:
    """What the Automation section shows."""
    cfg, state = get_settings(), get_state()
    last_check = _parse(state.get("last_check"))
    run = pipeline.get_run_state()
    auto_running = run.get("status") == "running" and run.get("kind") == "automation"
    fresh = bool(last_check and (now() - last_check) <= timedelta(minutes=SCHEDULER_STALE_MINUTES))
    next_run = _parse(state.get("next_run")) if cfg["enabled"] else None
    last_run = _parse(state.get("last_run"))
    return {
        "next_run_text": _fmt(next_run, "%a, %b %d, %Y · %I:%M %p"),
        "last_run_text": _fmt(last_run, "%b %d, %Y · %I:%M %p"),
        "last_check_text": _ago(last_check),
        "settings": cfg,
        "describe": describe(cfg),
        "next_run": next_run,
        "last_run": last_run,
        "last_result": state.get("last_result"),
        "last_error": state.get("last_error"),
        "last_check": last_check,
        "scheduler_active": fresh or auto_running,
        "running": auto_running,
        "tz_label": getattr(settings, "AUTOMATION_TIME_ZONE_LABEL", "PHT"),
    }


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------
def run_settings() -> dict:
    """The pipeline settings of an automatic run: the saved settings, the multiple search
    list, every step."""
    cfg = pipeline.get_extraction_settings()
    cfg.update(do_scrape=True, do_compile=True, do_extract=True, standardize=True, do_ghost=True)
    return pipeline.run_config(cfg, mode="multiple")


def tick(moment=None, force=False, wait=True) -> str:
    """One check of the schedule (what the timer runs). Starts the pipeline when a run is
    due (or right away with force=True), and with wait=True stays until it ends.
    Returns a line saying what happened."""
    moment = moment or now()
    cfg, state = get_settings(), get_state()
    state["last_check"] = moment.isoformat(timespec="seconds")
    _write(_state_file(), state)

    if not force:
        if not cfg["enabled"]:
            return "Automation is off."
        scheduled = _parse(state.get("next_run"))
        if scheduled is None:
            state["next_run"] = first_run_after(cfg, moment).isoformat()
            _write(_state_file(), state)
            return f"Next automatic run: {state['next_run']}."
        if moment < scheduled:
            return f"Not due yet; next automatic run: {scheduled.isoformat()}."
    else:
        scheduled = moment

    if pipeline.is_running():
        return "A run is already in progress; the automatic run will start at the next check after it ends."

    run_cfg = run_settings()
    error = pipeline.check_run_choices(run_cfg, mode="multiple")
    if error is None:
        state.update(last_run=moment.isoformat(timespec="seconds"), last_result="running", last_error=None)
        if cfg["enabled"] and not force:
            state["next_run"] = following_run(cfg, scheduled, moment).isoformat()
        _write(_state_file(), state)
        error = pipeline.start_run(run_cfg, kind="automation", wait=wait)
    state = get_state()
    if error:
        pipeline.log_to_console(f"Automatic run didn't start: {error}")
        state.update(last_run=moment.isoformat(timespec="seconds"), last_result="not started", last_error=error)
        if cfg["enabled"] and not force:
            state["next_run"] = following_run(cfg, scheduled, moment).isoformat()
        _write(_state_file(), state)
        return f"The automatic run didn't start: {error}"
    if wait:
        state["last_result"] = pipeline.get_run_state().get("status", "done")
        _write(_state_file(), state)
        return f"Automatic run ended: {state['last_result']}."
    return "Automatic run started."
