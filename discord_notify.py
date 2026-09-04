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
        try:
            response = requests.post(url, params={"wait": "true", "with_components": "true"}, json=payload, timeout=20)
        except requests.RequestException:
            raise RuntimeError("Discord transport failed; message remains pending where supported") from None
        if response.status_code == 429:
            retry_after = float(response.json().get("retry_after", 1))
            time.sleep(min(retry_after, 10))
            continue
        if response.status_code >= 500 and attempt < 2:
            time.sleep(2**attempt)
            continue
        if not response.ok:
            raise RuntimeError(f"Discord rejected message: HTTP {response.status_code}")
        break
    if response is None:
        raise RuntimeError("Discord webhook did not return a response")
    if not response.ok:
        raise RuntimeError(f"Discord rejected message: HTTP {response.status_code}")
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
                    parsed_start = datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
                    if parsed_start.tzinfo is None:
                        continue
                    video_start = parsed_start.astimezone(LOCAL_TZ)
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
                if video_day >= today or video.get("live_status") == "live":
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
        candidates = [event for event in current.get("events", []) if event.get("verified") is True]
        parsed: list[dict[str, Any]] = []
        for candidate in candidates:
            try:
                start = date.fromisoformat(candidate["start"])
                end = date.fromisoformat(candidate["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if end >= today:
                parsed.append({**candidate, "start": start, "end": end, "raw": str(candidate.get("raw", ""))})
        unique = {(item["start"], item["end"], item.get("label", "")): item for item in parsed}
        for item in sorted(unique.values(), key=lambda item: item["start"]):
            events.append(
                {
                    **item,
                    "series": source.get("name", source.get("id", "Drift")),
                    "label": item.get("label", "Wydarzenie"),
                    "watch_url": source.get("watch_url"),
                    "calendar_url": item.get("source_url", source.get("url")),
                    "is_live": False,
                }
            )
    return sorted(events, key=_event_sort_key)


def format_upcoming_digest(observations: list[tuple[dict[str, Any], Any]]) -> dict[str, Any]:
    events = _upcoming_events(observations)
    # Live first; then calendar dates and exact scheduled times.
    events.sort(key=lambda event: (not event.get("is_live"), _event_sort_key(event)))
    today = warsaw_today()
    fields = []
    buttons = []
    budget = 5000  # Discord's 6000-character total includes headings, footer, description.
    shown = 0
    for event in events[:16]:
        start, end = event["start"], event["end"]
        local = (
            datetime.fromisoformat(event["scheduled_at"].replace("Z", "+00:00")).astimezone(LOCAL_TZ)
            if event.get("scheduled_at")
            else None
        )
        tonight = local and local.hour < 6 and local.date() == today + timedelta(days=1)
        if event.get("is_live"):
            status = "🔴 LIVE TERAZ"
        elif tonight:
            status = "🌙 TEJ NOCY"
        elif start <= today <= end:
            status = "🔥 TO DZIŚ!"
        elif start == today + timedelta(days=1):
            status = "⏳ JUTRO"
        else:
            status = f"📅 ZA {(start - today).days} DNI"
        when = f"{start.day} {POLISH_MONTHS[start.month - 1]}"
        if end != start:
            when += f" – {end.day} {POLISH_MONTHS[end.month - 1]}"
        if local:
            when += f" · **{local:%H:%M}** · <t:{int(local.timestamp())}:R>"
        lines = [f"**{_clip(event['label'], 180)}**", when]
        if local and (night := _overnight_label(local)):
            lines.append(night)
        if event.get("venue"):
            lines.append(f"📍 {_clip(event['venue'], 140)}")
        if event.get("event_scope") == "weekend":
            lines.append("Weekend wraz z treningami — godzina transmisji osobno.")
        if event.get("verification") == "ocr_agreement":
            lines.append("📷 Termin z plakatu · zgodny odczyt OCR")
        links = []
        if event.get("watch_url"):
            label = "▶ Otwórz transmisję" if local else "Kanał organizatora"
            links.append(f"[{label}]({event['watch_url']})")
            if local and len(buttons) < 5 and event["watch_url"] not in [b["url"] for b in buttons]:
                buttons.append({"type": 2, "style": 5, "label": _watch_button_label(event), "url": event["watch_url"]})
        elif not local:
            lines.append("Transmisja: brak potwierdzonego linku.")
        if event.get("calendar_url"):
            links.append(f"[Oficjalny kalendarz]({event['calendar_url']})")
        if links:
            lines.append(" · ".join(links))
        field = {
            "name": _clip(f"{status} · {event['series']}", 256),
            "value": _clip("\n".join(lines), 1024),
            "inline": False,
        }
        cost = len(field["name"]) + len(field["value"])
        if cost > budget:
            break
        budget -= cost
        fields.append(field)
        shown += 1
    if not fields:
        fields = [
            {
                "name": "Na razie brak potwierdzonych terminów",
                "value": "Kolejny odczyt odbędzie się automatycznie. Nie publikuję niepewnych dat.",
                "inline": False,
            }
        ]
    payload = {
        "content": "🏁 **DRIFT RADAR** · Twój plan oglądania",
        "embeds": [
            {
                "title": "Najbliżej toru. Bez szukania.",
                "description": (
                    "🔴 trwające transmisje · 🌙 nocne starty · 🏁 nadchodzące rundy\n"
                    "Godziny w Polsce. Daty zawodów nie oznaczają godziny rozpoczęcia live."
                ),
                "color": 0x8B5CF6,
                "fields": fields,
                "footer": {"text": f"Pokazano {shown} z {len(events)} terminów · Europe/Warsaw · oficjalne źródła"},
                "timestamp": warsaw_now().isoformat(),
            }
        ],
    }
    if buttons:
        payload["components"] = [{"type": 1, "components": buttons}]
    return payload
