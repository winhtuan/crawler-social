"""Run the crawl on a cron schedule.

Entrypoint:  python -m crawlfb.scheduler

Reads ``schedule.json`` at the repo root::

    {"enabled": true, "cron": "0 2 * * *"}

Sleeps until the next fire and runs the same crawl the CLI runs today by
invoking ``run.py`` as a subprocess (rotate proxy -> crawl ``data/fb_pages.json``
-> upload S3). One crawl at a time: if the previous crawl is still running when a
fire arrives, the fire is skipped and logged. ``schedule.json`` is reloaded when
its mtime changes, so the schedule can be edited without restarting.

The crawl core, ``run.py``, and ``crawl.bat`` are unchanged — this only adds the
clock.

Run one crawl immediately and exit (no waiting for the schedule)::

    python -m crawlfb.scheduler --once
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from croniter import croniter

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEDULE_PATH = REPO_ROOT / "schedule.json"

DEFAULT_SCHEDULE = {"enabled": True, "cron": "0 2 * * *"}
_POLL_SECONDS = 5.0


def _load_schedule() -> dict:
    """Read schedule.json; any missing/invalid file falls back to the default."""
    try:
        raw = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return dict(DEFAULT_SCHEDULE)
    if not isinstance(raw, dict):
        return dict(DEFAULT_SCHEDULE)
    return raw


def _mtime() -> float:
    """Last-modified time of schedule.json, or 0.0 when the file is absent."""
    try:
        return SCHEDULE_PATH.stat().st_mtime
    except OSError:
        return 0.0


def _resolve_cron(schedule: dict) -> str:
    """Return a valid cron string from the schedule, falling back on invalid."""
    cron = schedule.get("cron") or DEFAULT_SCHEDULE["cron"]
    if not isinstance(cron, str):
        cron = DEFAULT_SCHEDULE["cron"]
    try:
        croniter(cron)
        return cron
    except (ValueError, KeyError):
        print(f"invalid cron {cron!r} - falling back to {DEFAULT_SCHEDULE['cron']!r}")
        return DEFAULT_SCHEDULE["cron"]


def _next_fire(cron: str) -> datetime:
    return croniter(cron, datetime.now()).get_next(datetime)


def _start_crawl() -> subprocess.Popen:
    """Launch the full crawl pipeline (run.py) in the background."""
    return subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "run.py")],
        cwd=str(REPO_ROOT),
    )


def run_once() -> int:
    """Run one crawl now and wait for it; return its exit code."""
    proc = _start_crawl()
    return proc.wait()


def run_loop() -> None:
    schedule = _load_schedule()
    last_mtime = _mtime()
    proc: subprocess.Popen | None = None

    print(f"scheduler started - schedule.json: {schedule}")
    while True:
        # Reap a finished crawl and log its exit before anything else.
        if proc is not None and proc.poll() is not None:
            print(f"[done] crawl exited {proc.returncode}")
            proc = None

        # Reload the schedule when the file changed.
        mtime = _mtime()
        if mtime != last_mtime:
            last_mtime = mtime
            schedule = _load_schedule()
            print(f"[reload] schedule.json -> {schedule}")

        if not schedule.get("enabled", True):
            time.sleep(_POLL_SECONDS)
            continue

        cron = _resolve_cron(schedule)
        next_fire = _next_fire(cron)

        # Tick toward next_fire in short steps so a schedule edit is honored
        # mid-wait (the break returns to the outer loop, which reloads).
        while datetime.now() < next_fire:
            remaining = (next_fire - datetime.now()).total_seconds()
            time.sleep(min(_POLL_SECONDS, remaining))
            if _mtime() != last_mtime:
                break
        if _mtime() != last_mtime:
            continue

        if proc is not None:
            # The previous crawl is still running — one crawl at a time.
            print(f"[skip] crawl still running at scheduled fire {next_fire:%Y-%m-%d %H:%M:%S}")
            time.sleep(_POLL_SECONDS)
            continue

        print(f"[fire] {datetime.now():%Y-%m-%d %H:%M:%S} -> run.py")
        proc = _start_crawl()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the crawl on a cron schedule")
    parser.add_argument(
        "--once",
        action="store_true",
        help="run one crawl now and exit (ignore the schedule)",
    )
    args = parser.parse_args()

    if args.once:
        return run_once()
    run_loop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
