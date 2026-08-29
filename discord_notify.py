from __future__ import annotations

import os
import re
import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

LOCAL_TZ = ZoneInfo("Europe/Warsaw")


def warsaw_now() -> datetime:
    return datetime.now(LOCAL_TZ)


def warsaw_today() -> date:
    return warsaw_now().date()


def _overnight_label(start: datetime) -> str:
    if start.hour >= 6:
        return ""
    previous = start.date() - timedelta(days=1)
    return f"🌙 **NOC Z {previous:%d.%m} NA {start:%d.%m}**"


def _discord_time(start: datetime) -> str:
    timestamp = int(start.timestamp())
    return f"<t:{timestamp}:F> · <t:{timestamp}:R>"


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _event_sort_key(event: dict[str, Any]) -> tuple[date, datetime, str]:
    scheduled = event.get("scheduled_at")
    if scheduled:
        sort_time = datetime.fromisoformat(scheduled.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
    else:
        sort_time = datetime.combine(event["start"], datetime.min.time(), LOCAL_TZ)
    return event["start"], sort_time, event["series"]


def _watch_button_label(event: dict[str, Any]) -> str:
    series = event["series"].replace(" YouTube", "")
    detail_match = next(
        (
            match
            for pattern in (r"Top\s*\d+", r"Qualifying", r"Finał|Finale", r"Rd\.?\s*\d+", r"Round\s*\d+")
            if (match := re.search(pattern, event["label"], re.I))
        ),
        None,
    )
    detail = detail_match.group(0) if detail_match else "Oglądaj"
    time_suffix = ""
    if event.get("scheduled_at"):
        local_start = datetime.fromisoformat(event["scheduled_at"].replace("Z", "+00:00")).astimezone(LOCAL_TZ)
        time_suffix = f" · {local_start:%H:%M}"
    return _clip(f"▶ {series} · {detail}{time_suffix}", 80)


def send_webhook(message: str | dict[str, Any], *, dry_run: bool = False) -> None:
    if dry_run:
        print(f"[dry-run] Discord: {message}")
        return
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not configured")
    payload = message if isinstance(message, dict) else {"content": message}
    payload.setdefault("allowed_mentions", {"parse": []})
    response = None
    for attempt in range(3):
        response = requests.post(url, json=payload, timeout=20)
        if response.status_code == 429:
            retry_after = float(response.json().get("retry_after", 1))
            time.sleep(min(retry_after, 10))
            continue
        if response.status_code >= 500 and attempt < 2:
            time.sleep(2**attempt)
            continue
        response.raise_for_status()
        break
    if response is None:
        raise RuntimeError("Discord webhook did not return a response")
    response.raise_for_status()
    if isinstance(payload, dict) and "embeds" in payload:
        print(
            "Discord accepted embed payload: "
            f"status={response.status_code}; embeds={len(payload.get('embeds', []))}; "
            f"components={len(payload.get('components', []))}"
        )


def format_change(source: dict[str, Any], before: Any, after: Any) -> dict[str, Any] | None:
    return format_change_digest([(source, after)])


def _polish_count(count: int, singular: str, paucal: str, plural: str) -> str:
    if count == 1:
        noun = singular
    elif count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        noun = paucal
    else:
        noun = plural
    return f"{count} {noun}"


def format_change_digest(observations: list[tuple[dict[str, Any], Any]]) -> dict[str, Any] | None:
    upcoming = [observation for observation in observations if _upcoming_events([observation])]
    if not upcoming:
        return None
    payload = format_upcoming_digest(upcoming)
    embed = payload["embeds"][0]
    embed["title"] = "🔔 DRIFT RADAR · Aktualizacja kalendarzy"
    source_count = _polish_count(len(upcoming), "źródle", "źródłach", "źródłach")
    calendar_count = _polish_count(len(upcoming), "kalendarz", "kalendarze", "kalendarzy")
    embed["description"] = f"Wykryto zmiany w {source_count}. Poniżej pokazuję wyłącznie aktualne, nadchodzące rundy."
    payload["content"] = f"🔔 **Drift Radar** · zaktualizowano {calendar_count}"
    return payload


def format_live_alert(source_name: str, video: dict[str, Any], minutes_until: int) -> dict[str, Any]:
    title = video.get("title", "Zaplanowana transmisja")
    start = datetime.fromisoformat(video["scheduled_start"].replace("Z", "+00:00")).astimezone(LOCAL_TZ)
    live = video.get("live_status") == "live"
    if live:
        status = "🔴 LIVE TERAZ"
        timing = "Transmisja już trwa — możesz wejść od razu."
    elif minutes_until >= 0:
        status = "⏰ START ZA CHWILĘ"
        timing = f"Planowany start za około **{minutes_until} min**."
    else:
        status = "🔴 SPRAWDŹ LIVE"
        timing = f"Planowany start był **{abs(minutes_until)} min temu** — transmisja może już trwać."
    night = _overnight_label(start)
    return {
        "content": f"{status} · **{source_name}**",
        "embeds": [
            {
                "title": f"{status} · {source_name}",
                "description": f"{timing}\n\n{_discord_time(start)}",
                "color": 0xE63946 if live else 0xFFB703,
                "fields": [
                    {"name": "🏁 Transmisja", "value": f"**{title}**", "inline": False},
                    {
                        "name": "🕒 Czas w Polsce",
                        "value": f"**{start:%d.%m.%Y · %H:%M}**" + (f"\n{night}" if night else ""),
                        "inline": False,
                    },
                ],
                "footer": {"text": "Drift Radar · Europe/Warsaw · automatyczny alert YouTube"},
                "timestamp": warsaw_now().isoformat(),
            }
        ],
        "components": [
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 5,
                        "label": "▶ Oglądaj LIVE",
                        "url": f"https://www.youtube.com/watch?v={video['id']}",
                    }
                ],
            }
        ],
    }


POLISH_MONTHS = [
    "stycznia",
    "lutego",
    "marca",
    "kwietnia",
    "maja",
    "czerwca",
    "lipca",
    "sierpnia",
    "września",
    "października",
    "listopada",
    "grudnia",
]


def _event_label(source: dict[str, Any], current: dict[str, Any], raw: str) -> str:
    text = " ".join(str(item) for item in current.get("items", []))
    day = re.search(r"\b(\d{1,2})", raw)
    month = re.search(
        r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|stycz|lut|mar|kwi|maj|cze|lip|sie|wrz|paź|lis|gru)",
        raw,
        re.I,
    )
    markers = list(
        re.finditer(r"(?:RND\s*\d+|RD\s*\d+|Round\s*\d+|Grand Finale|Finale|SPECIAL EVENT|Winter Training)", text, re.I)
    )
    if markers and day and month:
        nearby = [
            marker
            for marker in markers
            if day.group(1) in text[max(0, marker.start() - 250) : marker.end() + 250]
            and month.group(0).lower() in text[max(0, marker.start() - 250) : marker.end() + 250].lower()
        ]
        if nearby:
            date_anchor = re.search(
                rf"{re.escape(month.group(0))}\D{{0,5}}{re.escape(day.group(1))}",
                text,
                re.I,
            )
            anchor = date_anchor.start() if date_anchor else text.lower().find(month.group(0).lower())
            preceding = [marker for marker in nearby if marker.start() <= anchor]
            label = (
                preceding[-1] if preceding else min(nearby, key=lambda marker: abs(marker.start() - anchor))
            ).group(0)
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
    today = warsaw_today()
    now = warsaw_now()
    events: list[dict[str, Any]] = []
    for source, current in observations:
        if isinstance(current, list):
            for video in current:
                if not isinstance(video, dict):
                    continue
                scheduled = video.get("scheduled_start") or (
                    warsaw_now().isoformat() if video.get("live_status") == "live" else None
                )
                if not scheduled:
                    continue
                try:
                    video_start = datetime.fromisoformat(scheduled.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
                    video_day = video_start.date()
                except ValueError:
                    continue
                actual_end = video.get("actual_end")
                if actual_end:
                    try:
                        if datetime.fromisoformat(actual_end.replace("Z", "+00:00")).astimezone(LOCAL_TZ) <= now:
                            continue
                    except ValueError:
                        pass
                if video.get("live_status") == "none" and video_start < now:
                    continue
                if video_day >= today:
                    events.append(
                        {
                            "start": video_day,
                            "end": video_day,
                            "raw": video.get("title", ""),
                            "series": source.get("name", source.get("id", "Drift")),
                            "label": video.get("title", "Transmisja YouTube"),
                            "watch_url": f"https://www.youtube.com/watch?v={video.get('id')}",
                            "calendar_url": source.get("url"),
                            "is_live": video.get("live_status") == "live",
                            "scheduled_at": scheduled,
                        }
                    )
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
        for item in sorted(unique.values(), key=lambda item: item["start"]):
            events.append(
                {
                    **item,
                    "series": source.get("name", source.get("id", "Drift")),
                    "label": _event_label(source, current, item["raw"]),
                    "watch_url": source.get("watch_url"),
                    "calendar_url": source.get("url"),
                    "is_live": False,
                }
            )
    return sorted(events, key=_event_sort_key)


def format_upcoming_digest(observations: list[tuple[dict[str, Any], Any]]) -> dict[str, Any]:
    events = _upcoming_events(observations)
    today = warsaw_today()
    fields: list[dict[str, str]] = []
    watch_buttons: list[dict[str, Any]] = []
    calendar_buttons: list[dict[str, Any]] = []
    grouped: dict[date, list[dict[str, Any]]] = {}
    visible_events = events[:16]
    for event in visible_events:
        group_day = today if event["start"] < today <= event["end"] else event["start"]
        grouped.setdefault(group_day, []).append(event)
    for day, day_events in list(sorted(grouped.items()))[:12]:
        month = POLISH_MONTHS[day.month - 1]
        lines = []
        for event in day_events:
            when = (
                f"{event['start'].day} {month}"
                if event["start"] == event["end"]
                else f"{event['start'].day}–{event['end'].day} {month}"
            )
            if event.get("is_live"):
                urgency = "🔴 LIVE!"
            elif event["start"] <= today <= event["end"]:
                urgency = "🔥 TO DZIŚ!"
            elif (event["start"] - today).days == 1:
                urgency = "⏳ JUTRO"
            else:
                urgency = f"⏱️ za {(event['start'] - today).days} dni"
            scheduled_time = ""
            if event.get("scheduled_at"):
                local_start = datetime.fromisoformat(event["scheduled_at"].replace("Z", "+00:00")).astimezone(LOCAL_TZ)
                scheduled_time = f" · 🕒 **{local_start:%H:%M}** · <t:{int(local_start.timestamp())}:R>"
                night = _overnight_label(local_start)
            else:
                night = ""
            links = []
            if event["watch_url"]:
                links.append(f"[▶ Oglądaj]({event['watch_url']})")
            if event["calendar_url"]:
                links.append(f"[Kalendarz]({event['calendar_url']})")
            lines.append(
                f"**{urgency}**\n**{event['series']} · {event['label']}** ({when}{scheduled_time})"
                + (f"\n{night}" if night else "")
                + (f"\n{' · '.join(links)}" if links else "")
            )
            if event["watch_url"] and event["watch_url"] not in [button.get("url") for button in watch_buttons]:
                watch_buttons.append(
                    {
                        "type": 2,
                        "style": 5,
                        "label": _watch_button_label(event),
                        "url": event["watch_url"],
                    }
                )
            if event["calendar_url"] and event["calendar_url"] not in [
                button.get("url") for button in calendar_buttons
            ]:
                short_series = event["series"].replace(" YouTube", "")[:65]
                calendar_buttons.append(
                    {"type": 2, "style": 5, "label": f"📅 {short_series}", "url": event["calendar_url"]}
                )
        if day == today:
            day_heading = f"🔥 DZISIAJ · {day.day} {month} {day.year}"
        elif day == today + timedelta(days=1):
            day_heading = f"⏳ JUTRO · {day.day} {month} {day.year}"
        else:
            day_heading = f"📅 {day.day} {month} {day.year}"
        fields.append({"name": day_heading, "value": _clip("\n\n".join(lines), 1024), "inline": False})
    if not fields:
        fields.append(
            {
                "name": "Brak nadchodzących wydarzeń",
                "value": "Nie znaleziono przyszłych dat w aktualnych źródłach.",
                "inline": False,
            }
        )
    payload: dict[str, Any] = {
        "content": (
            f"🏁 **DRIFT RADAR** · {len(events)} nadchodzących transmisji i wydarzeń"
            + (f" · pokazuję najbliższe {len(visible_events)}" if len(events) > len(visible_events) else "")
        ),
        "embeds": [
            {
                "title": "🏁 DRIFT RADAR · Najbliższe wydarzenia",
                "description": (
                    "Najbliższe rundy i transmisje w jednym miejscu. "
                    "Godziny podaję w czasie polskim; Discord pokazuje też czas względny."
                ),
                "color": 0xE63946,
                "fields": fields,
                "footer": {"text": "Źródła oficjalne · strefa czasowa: Europe/Warsaw"},
                "timestamp": warsaw_now().isoformat(),
            }
        ],
    }
    buttons = (watch_buttons + calendar_buttons)[:5]
    if buttons:
        payload["components"] = [{"type": 1, "components": buttons}]
    return payload
