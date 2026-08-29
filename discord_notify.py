from __future__ import annotations

import os
from typing import Any

import requests


def send_webhook(message: str, *, dry_run: bool = False) -> None:
    if dry_run:
        print(f"[dry-run] Discord: {message}")
        return
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not configured")
    response = requests.post(url, json={"content": message}, timeout=20)
    response.raise_for_status()


def format_change(source_name: str, before: Any, after: Any) -> str:
    return (
        f"🔔 DRIFT RADAR — zmiana: {source_name}\n"
        f"Poprzedni odczyt: {before!r}\n"
        f"Aktualny odczyt: {after!r}"
    )

