from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
import yaml

from discord_notify import format_change_digest, format_live_alert, format_upcoming_digest, send_webhook
from parsers.generic import fetch_html, fetch_rss
from storage import read_state, safe_error, save_state

ROOT = Path(__file__).resolve().parent
STATE_PATH = Path(os.environ.get("DRIFT_STATE_PATH", str(ROOT / "data" / "state.json")))
SOURCES_PATH = ROOT / "sources.yaml"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_sources() -> list[dict[str, Any]]:
    data = yaml.safe_load(SOURCES_PATH.read_text(encoding="utf-8")) or {}
    sources = data.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("sources.yaml: 'sources' must be a list")
    ids: set[str] = set()
    for source in sources:
        if not isinstance(source, dict) or not source.get("id"):
            raise ValueError("Each source needs a stable 'id'")
        if source["id"] in ids:
            raise ValueError(f"Duplicate source id: {source['id']}")
        ids.add(source["id"])
    return sources


def fetch(source: dict[str, Any]) -> Any:
    kind = source.get("type")
    handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
        "rss": fetch_rss,
        "html": fetch_html,
    }
    if kind == "youtube":
        return fetch_youtube(source)
    if kind not in handlers:
        raise ValueError(f"Unsupported source type: {kind!r}")
    return handlers[kind](source)


def fetch_youtube(source: dict[str, Any]) -> list[dict[str, Any]]:
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise RuntimeError("YOUTUBE_API_KEY is not configured")

    def api_get(endpoint: str, params: dict[str, Any]) -> Any:
        quota = source.setdefault("_quota", {})
        day = datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
        if quota.get("day") != day:
            quota.update(day=day, used=0)
        if quota["used"] >= int(os.environ.get("YOUTUBE_DAILY_BUDGET", "8500")):
            raise RuntimeError("Local YouTube daily budget exhausted; retry after Pacific midnight")
        quota["used"] += 1
        return requests.get(f"https://www.googleapis.com/youtube/v3/{endpoint}", params=params, timeout=30)

    playlist_id = source.get("uploads_playlist_id")
    if not playlist_id and (source.get("channel_handle") or source.get("channel_username")):
        channel_params = {"part": "contentDetails", "key": key}
        if source.get("channel_handle"):
            channel_params["forHandle"] = source["channel_handle"]
        else:
            channel_params["forUsername"] = source["channel_username"]
        channel_response = api_get("channels", channel_params)
        channel_response.raise_for_status()
        channels = channel_response.json().get("items", [])
        if not channels:
            identity = source.get("channel_handle") or source.get("channel_username")
            raise RuntimeError(f"YouTube channel not found: {identity}")
        playlist_id = channels[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    if not playlist_id:
        raise ValueError("YouTube source needs uploads_playlist_id, channel_handle, or channel_username")
    source["uploads_playlist_id"] = playlist_id
    params = {"part": "snippet", "playlistId": playlist_id, "maxResults": 50, "key": key}
    response = api_get("playlistItems", params)
    response.raise_for_status()
    videos = [item["snippet"]["resourceId"]["videoId"] for item in response.json().get("items", [])]
    videos = list(dict.fromkeys([*source.get("tracked_video_ids", []), *videos]))
    if not videos:
        return []
    details = []
    for offset in range(0, len(videos), 50):
        detail_response = api_get(
            "videos",
            params={
                "part": "snippet,liveStreamingDetails,status",
                "id": ",".join(videos[offset : offset + 50]),
                "key": key,
            },
        )
        detail_response.raise_for_status()
        details.extend(detail_response.json().get("items", []))
    return [
        {
            "id": video["id"],
            "title": video.get("snippet", {}).get("title", ""),
            "published": video.get("snippet", {}).get("publishedAt", ""),
            "privacy_status": video.get("status", {}).get("privacyStatus"),
            "live_status": video.get("snippet", {}).get("liveBroadcastContent", "none"),
            "scheduled_start": video.get("liveStreamingDetails", {}).get("scheduledStartTime"),
            "actual_start": video.get("liveStreamingDetails", {}).get("actualStartTime"),
            "actual_end": video.get("liveStreamingDetails", {}).get("actualEndTime"),
        }
        for video in details
    ]


def prune_live_notifications(notifications: dict[str, Any], cutoff: datetime) -> dict[str, str]:
    kept: dict[str, str] = {}
    for key, sent_at in notifications.items():
        if not isinstance(sent_at, str):
            continue
        try:
            parsed = datetime.fromisoformat(sent_at)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            if parsed >= cutoff:
                kept[key] = sent_at
        except (TypeError, ValueError):
            continue
    return kept


def live_notification_key(source_id: str, video_id: str, scheduled: str, *, is_live: bool) -> str:
    stage = "live" if is_live else "pre"
    return f"{source_id}:{video_id}:{scheduled}:{stage}"


def run(
    *,
    dry_run: bool,
    bootstrap: bool,
    no_notify: bool,
    test_notification: bool,
    digest_notification: bool,
    source_type: str,
) -> int:
    state = read_state(STATE_PATH)
    old_sources = state.setdefault("sources", {})
    source_health = state.setdefault("source_health", {})
    youtube_cache = state.setdefault("youtube_cache", {})
    errors: list[str] = []
    observations: list[tuple[dict[str, Any], Any]] = []
    calendar_changes: list[tuple[dict[str, Any], Any]] = []
    live_notifications = state.setdefault("live_notifications", {})
    all_sources = load_sources()
    selected_sources = [
        source
        for source in all_sources
        if source_type == "all"
        or (source_type == "youtube" and source.get("type") == "youtube")
        or (source_type == "calendar" and source.get("type") != "youtube")
    ]
    active_sources = [source for source in selected_sources if source.get("enabled", True) is not False]
    now = datetime.now(UTC)
    notification_cutoff = now - timedelta(days=90)
    state["live_notifications"] = live_notifications = prune_live_notifications(
        live_notifications,
        notification_cutoff,
    )
    raw_last_youtube_check = state.get("last_youtube_check_at")
    try:
        last_youtube_check = (
            datetime.fromisoformat(raw_last_youtube_check) if raw_last_youtube_check else now - timedelta(minutes=15)
        )
        if last_youtube_check.tzinfo is None:
            last_youtube_check = last_youtube_check.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        last_youtube_check = now - timedelta(minutes=15)
    changed = 0
    successful = 0
    for source in selected_sources:
        if source.get("enabled", True) is False:
            print(f"[skip] {source['id']}: disabled pending source verification")
            continue
        source_id = source["id"]
        try:
            if source.get("type") == "youtube":
                source["_quota"] = state.setdefault("youtube_quota", {})
                source.update(youtube_cache.get(source_id, {}))
                source["tracked_video_ids"] = [
                    v["id"]
                    for v in old_sources.get(source_id, [])
                    if v.get("live_status") in ("live", "upcoming") and not v.get("actual_end")
                ]
            current = fetch(source)
            if source.get("uploads_playlist_id"):
                youtube_cache[source_id] = {"uploads_playlist_id": source["uploads_playlist_id"]}
            successful += 1
            source_health[source_id] = {"ok": True, "checked_at": datetime.now(UTC).isoformat()}
            observations.append((source, current))
            if source.get("type") == "youtube" and isinstance(current, list) and not no_notify:
                for video in current:
                    scheduled = video.get("scheduled_start") if isinstance(video, dict) else None
                    if not scheduled or not video.get("id"):
                        continue
                    if video.get("actual_end") or video.get("live_status") not in ("upcoming", "live"):
                        continue
                    start = datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
                    if start.tzinfo is None:
                        raise ValueError("YouTube timestamp has no timezone")
                    minutes_until = round((start - now).total_seconds() / 60)
                    is_live = video.get("live_status") == "live"
                    recently_missed = last_youtube_check <= start <= now and now - start <= timedelta(minutes=30)
                    if not is_live and not -10 <= minutes_until <= 10 and not recently_missed:
                        continue
                    notification_key = live_notification_key(
                        source_id,
                        video["id"],
                        scheduled,
                        is_live=is_live,
                    )
                    if notification_key in live_notifications:
                        continue
                    send_webhook(
                        format_live_alert(source.get("name", source_id), video, minutes_until),
                        dry_run=dry_run,
                    )
                    live_notifications[notification_key] = now.isoformat()
                    if not dry_run:
                        save_state(STATE_PATH, state)
            previous = old_sources.get(source_id)
            notify_source_change = source.get("type") != "youtube"
            if (
                previous is not None
                and event_signature(previous) != event_signature(current)
                and not no_notify
                and notify_source_change
            ):
                calendar_changes.append((source, current))
                changed += 1
            elif previous is not None and previous != current:
                changed += 1
            elif previous is None and not bootstrap and not no_notify and notify_source_change:
                calendar_changes.append((source, current))
                changed += 1
            elif previous is None and not bootstrap:
                changed += 1
            old_sources[source_id] = current
        except Exception as exc:  # keep other sources running; never erase good state
            error = safe_error(exc)
            errors.append(f"{source_id}: {error}")
            source_health[source_id] = {"ok": False, "checked_at": datetime.now(UTC).isoformat(), "error": error}
            print(f"[warning] {source_id}: {error}", file=sys.stderr)
    state["initialized"] = True
    if any(source.get("type") == "youtube" for source in active_sources):
        state["last_youtube_check_at"] = now.isoformat()
    if calendar_changes and not no_notify:
        pending = state.get("pending_calendar_notification", [])
        state["pending_calendar_notification"] = sorted(
            set(pending if isinstance(pending, list) else []) | {s["id"] for s, _ in calendar_changes}
        )
    if state.get("pending_calendar_notification") and not no_notify:
        if not dry_run:
            save_state(STATE_PATH, state)
        pending_ids = state["pending_calendar_notification"]
        fresh_pending = [(s, v) for s, v in observations if s["id"] in pending_ids]
        payload = format_change_digest(fresh_pending)
        if payload:
            send_webhook(payload, dry_run=dry_run)
        remaining = set(pending_ids) - {s["id"] for s, _ in fresh_pending}
        if remaining:
            state["pending_calendar_notification"] = sorted(remaining)
        else:
            state.pop("pending_calendar_notification", None)
    if test_notification and not no_notify:
        summary = (
            "✅ DRIFT RADAR — test połączenia Discord\n"
            f"Sprawdzono źródeł: {len(selected_sources)}; zmian: {changed}; błędów: {len(errors)}."
        )
        send_webhook(summary, dry_run=dry_run)
        print("Discord test notification sent")
    if digest_notification and not no_notify:
        send_webhook(format_upcoming_digest(observations), dry_run=dry_run)
        print("Discord data digest sent")
    if not dry_run:
        state["last_run"] = {
            "checked_at": datetime.now(UTC).isoformat(),
            "successful": successful,
            "errors": len(errors),
        }
        save_state(STATE_PATH, state)
    print(
        f"Checked {len(selected_sources)} source(s) in {source_type} mode; {changed} change(s); {len(errors)} error(s)."
    )
    return 1 if active_sources and successful == 0 else 0


def event_signature(value: Any) -> str:
    if not isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    # Text, OCR whitespace and sidebar changes must not trigger calendar spam.
    return json.dumps(value.get("events", []), sort_keys=True, ensure_ascii=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drift Radar personal monitor")
    parser.add_argument("--dry-run", action="store_true", help="do not write state or send Discord messages")
    parser.add_argument("--bootstrap", action="store_true", help="seed missing sources without notifications")
    parser.add_argument("--no-notify", action="store_true", help="write state but suppress Discord notifications")
    parser.add_argument("--test-notification", action="store_true", help="send one Discord connectivity/status message")
    parser.add_argument("--digest-notification", action="store_true", help="send one digest of currently read dates")
    parser.add_argument(
        "--source-type",
        choices=("all", "youtube", "calendar"),
        default="all",
        help="limit the scan to all, YouTube, or calendar sources",
    )
    args = parser.parse_args()
    raise SystemExit(
        run(
            dry_run=args.dry_run,
            bootstrap=args.bootstrap,
            no_notify=args.no_notify,
            test_notification=args.test_notification,
            digest_notification=args.digest_notification,
            source_type=args.source_type,
        )
    )
