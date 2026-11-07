#!/usr/bin/env python3
"""
Runs the Data > Data Extraction pipeline (scrape -> compile -> extract skills ->
standardize -> ghost job check) as ONE detached process, so a long run survives the Django dev server reloading.

It is started by myapp/pipeline/manager.py:    python -u orchestrator.py <run_config.json>

run_config.json:
    {"state_file": ..., "log_file": ..., "cwd": ..., "lane_labels": {lane: label},
     "steps": [{"name", "label", "argv": [...], "lane"?: ..., "slot"?: int, "continue_on_fail"?: bool}, ...],
     "finish_argv"?: [...]}     (run at the end whatever happened, e.g. the failed saves log)

Progress is written to state_file (JSON) with a heartbeat, and all step output goes to
log_file.  This file is deliberately standalone (stdlib only, no Django).
"""
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

HEARTBEAT_EVERY = 5  # seconds


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load(path):
    # On Windows a file can't be opened for a moment while another process swaps it in; retry.
    for attempt in range(40):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (PermissionError, ValueError):
            if attempt == 39:
                raise
            time.sleep(0.05)


def save(path, state):
    """Write via a temp file, then swap it in. On Windows the swap fails with 'Access is denied'
    whenever the web page is reading run.json at that instant, so retry for a while."""
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    for attempt in range(100):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05)
    try:    # last resort: write in place
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Runner:
    """Runs the steps in order. Consecutive steps that carry a "lane" (one lane per job source:
    its searches, then its compile step) run as parallel lanes, each lane in its own thread,
    with its output prefixed by the lane's label in the shared log. Searches that also carry a
    "slot" run their slots side by side inside the lane (see run_slots). A failed step with
    "continue_on_fail" (a single search) is marked failed and its lane goes on; any other
    failed step skips everything after it."""

    def __init__(self, cfg, state, log):
        self.cfg, self.state, self.log = cfg, state, log
        self.state_file = cfg["state_file"]
        self.lock = threading.RLock()
        self.env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        self.extra = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        self.final = "done"
        self.total = len(cfg["steps"])

    def save(self):
        with self.lock:
            self.state["heartbeat"] = now()
            running = [s["name"] for s in self.state["steps"] if s["status"] == "running"]
            self.state["current"] = ", ".join(running) or None
            save(self.state_file, self.state)

    def write(self, text):
        with self.lock:
            self.log.write(text)

    def run_step(self, i, prefix=""):
        """-> True when the step succeeded (or may fail without stopping its lane)."""
        step, rec = self.cfg["steps"][i], self.state["steps"][i]
        with self.lock:
            rec["status"] = "running"
            rec["started_at"] = now()
        self.save()
        self.write(f"\n=== Step {i + 1}/{self.total}: {step['label']} ===\n")
        if prefix:
            proc = subprocess.Popen(step["argv"], cwd=self.cfg["cwd"], env=self.env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace", **self.extra)
            for line in proc.stdout:
                self.write(prefix + line.rsplit("\r", 1)[-1].rstrip("\n") + "\n")
            proc.wait()
        else:
            proc = subprocess.Popen(step["argv"], cwd=self.cfg["cwd"], env=self.env, stdin=subprocess.DEVNULL,
                                    stdout=self.log, stderr=subprocess.STDOUT, **self.extra)
            last_beat = 0.0
            while proc.poll() is None:
                if time.time() - last_beat >= HEARTBEAT_EVERY:
                    self.save()
                    last_beat = time.time()
                time.sleep(0.5)
        with self.lock:
            rec["finished_at"] = now()
            rec["exit_code"] = proc.returncode
            if proc.returncode == 0:
                rec["status"] = "done"
                self.log.write(f"=== {prefix}{step['label']}: finished OK ===\n")
            else:
                rec["status"] = "failed"
                self.final = "failed"
                if step.get("continue_on_fail"):
                    self.log.write(f"=== {prefix}{step['label']}: FAILED (exit code {proc.returncode}) - "
                                   "going on with the next one ===\n")
                else:
                    self.log.write(f"=== {prefix}{step['label']}: FAILED (exit code {proc.returncode}) - "
                                   "later steps skipped ===\n")
        self.save()
        return proc.returncode == 0 or bool(step.get("continue_on_fail"))

    def skip(self, indexes):
        with self.lock:
            for j in indexes:
                if self.state["steps"][j]["status"] == "pending":
                    self.state["steps"][j]["status"] = "skipped"

    def run_slots(self, indexes, label):
        """Steps of one lane that carry a "slot" (one source's searches, dealt out to slots):
        each slot runs its steps in order in its own thread, the slots at the same time.
        -> True when every slot got through (a search with continue_on_fail may fail)."""
        slots = {}
        for i in indexes:
            slots.setdefault(self.cfg["steps"][i]["slot"], []).append(i)
        ok = {}

        def slot_worker(slot, items):
            for n, i in enumerate(items):
                if not self.run_step(i, f"[{label} {slot}] "):
                    self.skip(items[n + 1:])
                    ok[slot] = False
                    return
            ok[slot] = True

        threads = [threading.Thread(target=slot_worker, args=(slot, items), daemon=True)
                   for slot, items in slots.items()]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return all(ok.get(slot) for slot in slots)

    def run_lanes(self, indexes):
        lanes = {}
        for i in indexes:
            lanes.setdefault(self.cfg["steps"][i]["lane"], []).append(i)
        labels = self.cfg.get("lane_labels") or {}
        ok = {}

        def lane_worker(lane, items):
            label = labels.get(lane, lane)
            prefix = f"[{label}] " if len(lanes) > 1 else ""
            n = 0
            while n < len(items):
                if self.cfg["steps"][items[n]].get("slot"):
                    m = n
                    while m < len(items) and self.cfg["steps"][items[m]].get("slot"):
                        m += 1
                    good = self.run_slots(items[n:m], label)
                else:
                    m = n + 1
                    good = self.run_step(items[n], prefix)
                if not good:
                    self.skip(items[m:])
                    ok[lane] = False
                    return
                n = m
            ok[lane] = True

        threads = [threading.Thread(target=lane_worker, args=(lane, items), daemon=True)
                   for lane, items in lanes.items()]
        for t in threads:
            t.start()
        while any(t.is_alive() for t in threads):
            self.save()
            for t in threads:
                t.join(HEARTBEAT_EVERY / len(threads))
        return all(ok.get(lane) for lane in lanes)

    def run(self):
        steps, i = self.cfg["steps"], 0
        while i < len(steps):
            if steps[i].get("lane"):
                j = i
                while j < len(steps) and steps[j].get("lane"):
                    j += 1
                good = self.run_lanes(list(range(i, j)))
            else:
                j = i + 1
                good = self.run_step(i)
            if not good:
                self.skip(range(j, len(steps)))
                break
            i = j


def finish(cfg, log):
    """The run's closing command (the failed saves log), whatever happened to the steps."""
    argv = cfg.get("finish_argv")
    if not argv:
        return
    log.write("\n")
    try:
        extra = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        subprocess.run(argv, cwd=cfg["cwd"], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                       env=dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8"), timeout=300, **extra)
    except (OSError, subprocess.SubprocessError) as exc:
        log.write(f"Couldn't write the failed saves log: {exc}\n")


def main():
    cfg = load(sys.argv[1])
    state_file, log_file = cfg["state_file"], cfg["log_file"]
    state = load(state_file)
    state.update(pid=os.getpid(), heartbeat=now())
    save(state_file, state)

    with open(log_file, "a", encoding="utf-8", errors="replace", buffering=1) as log:
        runner = Runner(cfg, state, log)
        try:
            runner.run()
        finally:
            finish(cfg, log)

    state.update(status=runner.final, current=None, finished_at=now(), heartbeat=now())
    save(state_file, state)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # never die silently: surface it in the UI (and in the console log)
        import traceback
        try:
            st = load(sys.argv[1])
            try:
                with open(st["log_file"], "a", encoding="utf-8", errors="replace") as lf:
                    lf.write("\n[ERROR] The run crashed:\n" + traceback.format_exc())
            except OSError:
                pass
            s = load(st["state_file"])
            s.update(status="failed", current=None, finished_at=now(), error=f"{type(exc).__name__}: {exc}")
            save(st["state_file"], s)
        finally:
            raise
