"""JSON files the Recommendations Lab keeps in data/.state/ (no database tables)."""
import json
import threading

from ..pipeline import manager as pipeline

_LOCK = threading.Lock()


def path(name):
    return pipeline.state_dir() / f"recs_lab_{name}.json"


def load(name, default=None):
    try:
        data = json.loads(path(name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {} if default is None else default
    return data if isinstance(data, dict) else ({} if default is None else default)


def save(name, data):
    p = path(name)
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)


def update(name, fn):
    """Read, change with fn(data), save; returns the saved data."""
    with _LOCK:
        data = load(name)
        fn(data)
        p = path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    return data
