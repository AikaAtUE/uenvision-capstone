#!/usr/bin/env python3
"""
Runs the Data > Scrape Data pipeline (scrape -> compile -> extract skills) as ONE
detached process, so a long run survives the Django dev server reloading.

It is started by myapp/pipeline/manager.py:    python -u orchestrator.py <run_config.json>

run_config.json:
    {"state_file": ..., "log_file": ..., "cwd": ..., "steps": [{"name","label","argv":[...]}, ...]}

Progress is written to state_file (JSON) with a heartbeat, and all step output goes to
log_file.  This file is deliberately standalone (stdlib only, no Django).
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

HEARTBEAT_EVERY = 5  # seconds


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


def main():
    cfg = load(sys.argv[1])
    state_file, log_file, cwd = cfg["state_file"], cfg["log_file"], cfg["cwd"]
    state = load(state_file)
    state.update(pid=os.getpid(), heartbeat=now())
    save(state_file, state)

    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", TQDM_DISABLE="1")
    steps = state["steps"]
    final = "done"

    with open(log_file, "a", encoding="utf-8", errors="replace", buffering=1) as log:
        for i, step in enumerate(cfg["steps"]):
            state["current"] = step["name"]
            steps[i]["status"] = "running"
            steps[i]["started_at"] = now()
            save(state_file, state)

            log.write(f"\n=== Step {i + 1}/{len(cfg['steps'])}: {step['label']} ===\n")
            proc = subprocess.Popen(
                step["argv"], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT,
            )
            last_beat = 0.0
            while proc.poll() is None:
                if time.time() - last_beat >= HEARTBEAT_EVERY:
                    state["heartbeat"] = now()
                    save(state_file, state)
                    last_beat = time.time()
                time.sleep(0.5)

            steps[i]["finished_at"] = now()
            steps[i]["exit_code"] = proc.returncode
            if proc.returncode == 0:
                steps[i]["status"] = "done"
                log.write(f"=== {step['label']}: finished OK ===\n")
            else:
                steps[i]["status"] = "failed"
                log.write(f"=== {step['label']}: FAILED (exit code {proc.returncode}) - later steps skipped ===\n")
                for later in steps[i + 1:]:
                    later["status"] = "skipped"
                final = "failed"
                save(state_file, state)
                break
            save(state_file, state)

    state.update(status=final, current=None, finished_at=now(), heartbeat=now())
    save(state_file, state)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # never die silently: surface it in the UI
        try:
            st = load(sys.argv[1])
            s = load(st["state_file"])
            s.update(status="failed", current=None, finished_at=now(), error=f"{type(exc).__name__}: {exc}")
            save(st["state_file"], s)
        finally:
            raise
