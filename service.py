"""Always-on process supervisor; independent calendar and YouTube workers."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from discord_notify import format_upcoming_digest, send_webhook, warsaw_now
from main import load_sources
from storage import read_state, safe_error, save_state

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DRIFT_DATA_DIR", str(ROOT / "data")))
STOP = threading.Event()


def fresh_observations() -> list:
    sources = {s["id"]: s for s in load_sources() if s.get("enabled", True)}
    observations = []
    for mode in ("calendar", "youtube"):
        state = read_state(DATA / f"{mode}.json")
        for source_id, value in state.get("sources", {}).items():
            health = state.get("source_health", {}).get(source_id, {})
            stamp = health.get("checked_at")
            if source_id not in sources or not health.get("ok") or not stamp:
                continue
            max_age = timedelta(minutes=15) if mode == "youtube" else timedelta(hours=24)
            if datetime.now(UTC) - datetime.fromisoformat(stamp) <= max_age:
                observations.append((sources[source_id], value))
    return observations


def worker(mode: str, interval: int, once: bool, dry_run: bool) -> bool:
    while not STOP.is_set():
        started = time.monotonic()
        status = {"started_at": datetime.now(UTC).isoformat(), "ok": False}
        try:
            env = {**os.environ, "DRIFT_STATE_PATH": str((DATA / f"{mode}.json").resolve())}
            args = [sys.executable, str(ROOT / "main.py"), "--source-type", mode, "--bootstrap"]
            if dry_run:
                args.append("--dry-run")
            # Calendar errors or OCR cannot block the independent live worker.
            result = subprocess.run(args, env=env, cwd=ROOT, timeout=240 if mode == "youtube" else 1800, check=False)
            status.update(ok=result.returncode == 0, exit_code=result.returncode)
        except Exception as exc:
            status["error"] = safe_error(exc)
            print(json.dumps({"worker": mode, **status}), flush=True)
        status["finished_at"] = datetime.now(UTC).isoformat()
        if not dry_run:
            save_state(DATA / f"health-{mode}.json", status)
        if once:
            return status["ok"]
        STOP.wait(max(1, interval - (time.monotonic() - started)))
    return True


def daily_digest() -> None:
    path = DATA / "digest.json"
    while not STOP.is_set():
        try:
            now = warsaw_now()
            slot = f"{now:%Y-%m-%d}:{now.hour}"
            if now.hour in (9, 19):
                state = read_state(path)
                if state.get("last_slot") != slot:
                    observations = fresh_observations()
                    if observations:
                        send_webhook(format_upcoming_digest(observations))
                        save_state(path, {"last_slot": slot})
        except Exception as exc:
            print(f"Digest error: {safe_error(exc)}", flush=True)
        STOP.wait(60)


def healthcheck() -> int:
    for mode, limit in (("youtube", 900), ("calendar", 10 * 3600)):
        state = read_state(DATA / f"health-{mode}.json")
        finished = state.get("finished_at")
        if not finished or not state.get("ok"):
            return 1
        if (datetime.now(UTC) - datetime.fromisoformat(finished)).total_seconds() > limit:
            return 1
    return 0


def serve(once: bool = False, dry_run: bool = False, mode: str = "all") -> int:
    if not dry_run and any(not os.environ.get(key) for key in ("YOUTUBE_API_KEY", "DISCORD_WEBHOOK_URL")):
        raise RuntimeError("Set YOUTUBE_API_KEY and DISCORD_WEBHOOK_URL in the service environment")
    DATA.mkdir(parents=True, exist_ok=True)
    # Linux host/container lock prevents duplicate daemons on the same volume.
    lock = (DATA / "service.lock").open("a+")
    if os.name == "posix":
        import fcntl

        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    threads = []
    results = {}

    def run_worker(name: str, interval: int) -> None:
        try:
            results[name] = worker(name, interval, once, dry_run)
        except Exception as exc:
            # A failed state write must not leave a silently dead worker thread.
            print(f"Worker stopped: {name}: {safe_error(exc)}", flush=True)
            results[name] = False
            STOP.set()

    for name, interval in (("youtube", 300), ("calendar", 8 * 3600)):
        if mode not in ("all", name):
            continue
        thread = threading.Thread(target=run_worker, args=(name, interval), name=name)
        thread.start()
        threads.append(thread)
    if not once and not dry_run:
        thread = threading.Thread(target=daily_digest, name="digest")
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()
    lock.close()
    return 1 if not all(results.values()) else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="one finite verification cycle")
    parser.add_argument("--dry-run", action="store_true", help="no Discord messages or state writes")
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--source-type", choices=("all", "calendar", "youtube"), default="all")
    args = parser.parse_args()
    raise SystemExit(healthcheck() if args.healthcheck else serve(args.once, args.dry_run, args.source_type))
