from __future__ import annotations

import json
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_html_sources_have_structured_date_candidates() -> None:
    state = json.loads((ROOT / "state.json").read_text(encoding="utf-8"))
    html_entries = [value for key, value in state["sources"].items() if key.endswith("calendar")]
    assert html_entries, "No HTML source state found"
    for entry in html_entries:
        assert isinstance(entry, dict), "HTML source state must be an object"
        candidates = entry.get("date_candidates")
        assert candidates, (
            "Every calendar source must expose date_candidates; raw page text is not a date output"
        )
        for candidate in candidates:
            start = date.fromisoformat(candidate["start"])
            end = date.fromisoformat(candidate["end"])
            assert start <= end
