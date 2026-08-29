from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class StateContractTests(unittest.TestCase):
    def test_calendar_state_has_valid_structured_dates(self) -> None:
        state = json.loads((ROOT / "state.json").read_text(encoding="utf-8"))
        html_entries = [value for key, value in state["sources"].items() if key.endswith("calendar")]
        self.assertTrue(html_entries, "No HTML source state found")
        with_dates = 0
        for entry in html_entries:
            self.assertIsInstance(entry, dict, "HTML source state must be an object")
            candidates = entry.get("date_candidates") or entry.get("ocr_date_candidates") or []
            if candidates:
                with_dates += 1
            for candidate in candidates:
                start = date.fromisoformat(candidate["start"])
                end = date.fromisoformat(candidate["end"])
                self.assertLessEqual(start, end)
        self.assertGreaterEqual(with_dates / len(html_entries), 0.8)


if __name__ == "__main__":
    unittest.main()
