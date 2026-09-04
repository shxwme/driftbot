"""One bounded job, launched only by an authenticated HTTP request."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta

import main
from cloud_store import assert_lease, read_remote, write_remote
from discord_notify import format_upcoming_digest, send_webhook, warsaw_now


def calendar_source(state: dict, sources: list, now: datetime) -> str | None:
    due = []
    for source in sources:
        if source.get("type") == "youtube" or not source.get("enabled", True):
            continue
        health = state.get("source_health", {}).get(source["id"], {})
        raw = health.get("checked_at")
        stamp = datetime.fromisoformat(raw) if raw else datetime.min.replace(tzinfo=UTC)
        delay = timedelta(hours=8) if health.get("ok") else timedelta(minutes=30)
        if now - stamp >= delay:
            due.append((stamp, source["id"]))
    return min(due)[1] if due else None


def digest() -> int:
    now = warsaw_now()
    if now.hour not in (9, 19):
        return 0
    name = os.environ["DRIFT_REMOTE_STATE_KEY"]
    token = os.environ["DRIFT_JOB_TOKEN"]
    state = read_remote(name)
    slot = f"{now:%Y-%m-%d}:{now.hour}"
    if state.get("last_slot") == slot:
        return 0
    sources = {s["id"]: s for s in main.load_sources() if s.get("enabled", True)}
    observations = []
    for kind in ("youtube", "calendar"):
        current = read_remote(kind)
        age = timedelta(minutes=15) if kind == "youtube" else timedelta(hours=24)
        for source_id, value in current.get("sources", {}).items():
            health = current.get("source_health", {}).get(source_id, {})
            raw = health.get("checked_at")
            if source_id in sources and health.get("ok") and raw and now - datetime.fromisoformat(raw) <= age:
                observations.append((sources[source_id], value))
    if observations:
        assert_lease()
        send_webhook(format_upcoming_digest(observations))
        write_remote(name, token, {"last_slot": slot})
    return 0


def run(kind: str) -> int:
    assert_lease()
    if kind == "digest":
        return digest()
    if kind == "calendar":
        source_id = calendar_source(read_remote("calendar"), main.load_sources(), datetime.now(UTC))
        if not source_id:
            return 0
        os.environ["DRIFT_SOURCE_ID"] = source_id
    return main.run(
        dry_run=False,
        bootstrap=True,
        no_notify=False,
        test_notification=False,
        digest_notification=False,
        source_type=kind,
    )


if __name__ == "__main__":
    from storage import safe_error

    try:
        raise SystemExit(run(sys.argv[1]))
    except Exception as exc:
        print(safe_error(exc), file=sys.stderr)
        raise SystemExit(1) from None
