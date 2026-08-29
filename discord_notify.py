from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

LOCAL_TZ = ZoneInfo("Europe/Warsaw")


def send_webhook(message: str | dict[str, Any], *, dry_run: bool = False) -> None:
    if dry_run:
        print(f"[dry-run] Discord: {message}")
        return
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not configured")
    payload = message if isinstance(message, dict) else {"content": message}
    response = requests.post(url, json=payload, timeout=20)
    response.raise_for_status()
    if isinstance(payload, dict) and "embeds" in payload:
        print(
            "Discord accepted embed payload: "
            f"status={response.status_code}; embeds={len(payload.get('embeds', []))}; "
            f"components={len(payload.get('components', []))}"
        )


def format_change(source: dict[str, Any], before: Any, after: Any) -> dict[str, Any]:
    source_name = source.get("name", source.get("id", "źródło"))
    payload = format_upcoming_digest([(source, after)]) if isinstance(after, dict) else {
        "embeds": [{"title": f"🔔 DRIFT RADAR · zmiana: {source_name}", "description": "Wykryto aktualizację źródła."}]
    }
    embed = payload["embeds"][0]
    embed["title"] = f"🔔 DRIFT RADAR · aktualizacja: {source_name}"
    embed["description"] = "Wykryto zmianę w źródle. Poniżej pokazano tylko aktualne, nadchodzące daty."
    payload["content"] = f"🔔 Drift Radar: aktualizacja danych — {source_name}"
    return payload


def format_live_alert(source_name: str, video: dict[str, Any], minutes_until: int) -> dict[str, Any]:
    title = video.get("title", "Zaplanowana transmisja")
    start = datetime.fromisoformat(video["scheduled_start"].replace("Z", "+00:00")).astimezone(LOCAL_TZ)
    live = video.get("live_status") == "live"
    status = "🔴 LIVE!" if live else "⏰ START ZA CHWILĘ"
    night = f"🌙 NOC Z {(start.date() - timedelta(days=1)):%d.%m} NA {start:%d.%m}!" if start.hour < 6 else ""
    timing = "Transmisja właśnie trwa." if live else f"Start planowany za około {max(0, minutes_until)} min · {start:%d.%m.%Y %H:%M} (Europe/Warsaw)"
    return {
        "content": f"{status} · {source_name} · {title}",
        "embeds": [{
            "title": f"{status} · {source_name}",
            "description": timing,
            "color": 0xE63946 if live else 0xFFB703,
            "fields": [{"name": "Transmisja", "value": f"**{title}**\n📅 {start:%d.%m.%Y} · 🕒 {start:%H:%M}" + (f"\n{night}" if night else ""), "inline": False}],
            "footer": {"text": "Drift Radar · automatyczny alert YouTube"},
            "timestamp": datetime.now().astimezone().isoformat(),
        }],
        "components": [{"type": 1, "components": [{"type": 2, "style": 5, "label": "▶ Oglądaj LIVE", "url": f"https://www.youtube.com/watch?v={video['id']}"}]}],
    }


POLISH_MONTHS = [
    "stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
    "lipca", "sierpnia", "września", "października", "listopada", "grudnia",
]


def _event_label(source: dict[str, Any], current: dict[str, Any], raw: str) -> str:
    text = " ".join(str(item) for item in current.get("items", []))
    day = re.search(r"\b(\d{1,2})", raw)
    month = re.search(r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|stycz|lut|mar|kwi|maj|cze|lip|sie|wrz|paź|lis|gru)", raw, re.I)
    markers = list(re.finditer(r"(?:RND\s*\d+|RD\s*\d+|Round\s*\d+|Grand Finale|Finale|SPECIAL EVENT|Winter Training)", text, re.I))
    if markers and day and month:
        nearby = [
            marker for marker in markers
            if day.group(1) in text[max(0, marker.start() - 250): marker.end() + 250]
            and month.group(0).lower() in text[max(0, marker.start() - 250): marker.end() + 250].lower()
        ]
        if nearby:
            date_anchor = re.search(
                rf"{re.escape(month.group(0))}\D{{0,5}}{re.escape(day.group(1))}",
                text,
                re.I,
            )
            anchor = date_anchor.start() if date_anchor else text.lower().find(month.group(0).lower())
            preceding = [marker for marker in nearby if marker.start() <= anchor]
            label = (preceding[-1] if preceding else min(nearby, key=lambda marker: abs(marker.start() - anchor))).group(0)
            normalized = re.sub(r"^RND\s*|^RD\s*|^Round\s*", "", label, flags=re.I)
            if label.lower().startswith("special"):
                return "Event specjalny"
            if label.lower().startswith("winter"):
                return "Trening zimowy"
            if "finale" in label.lower():
                return "Wielki finał"
            return f"Runda {normalized}" if normalized.isdigit() else label.title()
    return source.get("event_label", "Wydarzenie")


def _upcoming_events(observations: list[tuple[dict[str, Any], Any]]) -> list[dict[str, Any]]:
    today = date.today()
    events: list[dict[str, Any]] = []
    for source, current in observations:
        if isinstance(current, list):
            for video in current:
                if not isinstance(video, dict):
                    continue
                scheduled = video.get("scheduled_start") or (datetime.now().astimezone().isoformat() if video.get("live_status") == "live" else None)
                if not scheduled:
                    continue
                try:
                    video_start = datetime.fromisoformat(scheduled.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
                    video_day = video_start.date()
                except ValueError:
                    continue
                if video_day >= today:
                    events.append({
                        "start": video_day,
                        "end": video_day,
                        "raw": video.get("title", ""),
                        "series": source.get("name", source.get("id", "Drift")),
                        "label": video.get("title", "Transmisja YouTube"),
                        "watch_url": f"https://www.youtube.com/watch?v={video.get('id')}",
                        "calendar_url": source.get("url"),
                        "is_live": video.get("live_status") == "live",
                        "scheduled_at": scheduled,
                    })
            continue
        if not isinstance(current, dict):
            continue
        candidates = current.get("date_candidates") or current.get("ocr_date_candidates") or []
        parsed: list[dict[str, Any]] = []
        for candidate in candidates:
            try:
                start = date.fromisoformat(candidate["start"])
                end = date.fromisoformat(candidate["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if end >= today:
                parsed.append({"start": start, "end": end, "raw": str(candidate.get("raw", ""))})
        unique: dict[tuple[date, date], dict[str, Any]] = {(item["start"], item["end"]): item for item in parsed}
        for item in list(unique.values()):
            if item["start"] == item["end"] and any(
                other["start"] <= item["start"] <= other["end"] and other["start"] != other["end"]
                for other in unique.values()
            ):
                unique.pop((item["start"], item["end"]), None)
        ordered = sorted(unique.values(), key=lambda item: item["start"])
        merged: list[dict[str, Any]] = []
        for item in ordered:
            if merged and merged[-1]["start"] == merged[-1]["end"] and item["start"] == merged[-1]["end"] + timedelta(days=1) and item["start"] == item["end"]:
                merged[-1]["end"] = item["end"]
            else:
                merged.append(item)
        for item in merged:
            events.append({
                **item,
                "series": source.get("name", source.get("id", "Drift")),
                "label": _event_label(source, current, item["raw"]),
                "watch_url": source.get("watch_url"),
                "calendar_url": source.get("url"),
                "is_live": False,
            })
    return sorted(events, key=lambda item: (item["start"], item["series"]))


def format_upcoming_digest(observations: list[tuple[dict[str, Any], Any]]) -> dict[str, Any]:
    events = _upcoming_events(observations)
    fields: list[dict[str, str]] = []
    buttons: list[dict[str, Any]] = []
    grouped: dict[date, list[dict[str, Any]]] = {}
    for event in events[:16]:
        grouped.setdefault(event["start"], []).append(event)
    for day, day_events in list(sorted(grouped.items()))[:12]:
        month = POLISH_MONTHS[day.month - 1]
        lines = []
        for event in day_events:
            when = f"{event['start'].day} {month}" if event["start"] == event["end"] else f"{event['start'].day}–{event['end'].day} {month}"
            if event.get("is_live"):
                urgency = "🔴 LIVE!"
            elif event["start"] <= date.today() <= event["end"]:
                urgency = "🔥 TO DZIŚ!"
            elif (event["start"] - date.today()).days == 1:
                urgency = "⏳ JUTRO"
            else:
                urgency = f"⏱️ za {(event['start'] - date.today()).days} dni"
            scheduled_time = ""
            if event.get("scheduled_at"):
                local_start = datetime.fromisoformat(event['scheduled_at'].replace('Z', '+00:00')).astimezone(LOCAL_TZ)
                scheduled_time = f" · 🕒 {local_start:%H:%M}"
                if local_start.hour < 6:
                    scheduled_time += f" · 🌙 noc z {(local_start.date() - timedelta(days=1)):%d.%m} na {local_start:%d.%m}"
            links = []
            if event["watch_url"]:
                links.append(f"[▶ Oglądaj]({event['watch_url']})")
            if event["calendar_url"]:
                links.append(f"[Kalendarz]({event['calendar_url']})")
            lines.append(f"**{urgency} · {event['series']} · {event['label']}** ({when}{scheduled_time})" + (f"\n{' · '.join(links)}" if links else ""))
            if event["watch_url"] and event["watch_url"] not in [button.get("url") for button in buttons]:
                buttons.append({"type": 2, "style": 5, "label": "Oglądaj", "url": event["watch_url"]})
            if event["calendar_url"] and event["calendar_url"] not in [button.get("url") for button in buttons]:
                buttons.append({"type": 2, "style": 5, "label": "Kalendarz", "url": event["calendar_url"]})
        fields.append({"name": f"📅 {day.day} {month} {day.year}", "value": "\n".join(lines), "inline": False})
    if not fields:
        fields.append({"name": "Brak nadchodzących wydarzeń", "value": "Nie znaleziono przyszłych dat w aktualnych źródłach.", "inline": False})
    payload: dict[str, Any] = {
        "content": "🏁 DRIFT RADAR v3 · najbliższe wydarzenia — szczegóły i przyciski są w karcie poniżej.",
        "embeds": [{
            "title": "🏁 DRIFT RADAR · Najbliższe wydarzenia",
            "description": "Automatyczny przegląd przyszłych rund i eventów. Daty minione są pomijane.",
            "color": 0xE63946,
            "fields": fields,
            "footer": {"text": "Źródła oficjalne · strefa czasowa: Europe/Warsaw"},
            "timestamp": datetime.now().astimezone().isoformat(),
        }],
    }
    if buttons:
        payload["components"] = [{"type": 1, "components": buttons[:5]}]
    return payload
