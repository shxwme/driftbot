"""Crash-safe private runtime state. Never commit runtime data back to Git."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"sources": {}}
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError("Runtime state must be a JSON object")
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def safe_error(exc: Exception) -> str:
    # requests exceptions can contain both the Google key and the webhook token.
    message = str(exc)
    for variable in ("DISCORD_WEBHOOK_URL", "YOUTUBE_API_KEY"):
        value = os.environ.get(variable)
        if value:
            message = message.replace(value, "<REDACTED>")
    return f"{type(exc).__name__}: {message}"
