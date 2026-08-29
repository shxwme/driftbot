from __future__ import annotations

import json
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
state = json.loads((ROOT / "state.json").read_text(encoding="utf-8"))
missing: list[str] = []
invalid: list[str] = []
for source_id, entry in state["sources"].items():
    if not source_id.endswith("calendar"):
        continue
    candidates = entry.get("date_candidates", [])
    if not candidates:
        missing.append(source_id)
        continue
    for candidate in candidates:
        try:
            start = date.fromisoformat(candidate["start"])
            end = date.fromisoformat(candidate["end"])
            if start > end:
                invalid.append(f"{source_id}: {candidate}")
        except (KeyError, TypeError, ValueError):
            invalid.append(f"{source_id}: {candidate}")

print(f"calendar_sources={len([key for key in state['sources'] if key.endswith('calendar')])}")
print(f"with_valid_dates={len([key for key in state['sources'] if key.endswith('calendar')]) - len(missing) - len(invalid)}")
print(f"missing_dates={len(missing)}: {', '.join(missing) if missing else 'none'}")
print(f"invalid_dates={len(invalid)}: {', '.join(invalid) if invalid else 'none'}")
raise SystemExit(1 if invalid else 2 if missing else 0)
