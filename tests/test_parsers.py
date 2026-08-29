from __future__ import annotations

import unittest

from parsers.generic import extract_date_candidates


class DateParserTests(unittest.TestCase):
    def test_ocr_day_range_before_month_uses_default_year(self) -> None:
        candidates = extract_date_candidates(
            "24-26 APRIL NURBURGRING 11-12 JULY MARIAPOCS 16-18 OCTOBER ACHNA",
            default_year=2026,
        )
        ranges = {(item["start"], item["end"]) for item in candidates}
        self.assertIn(("2026-04-24", "2026-04-26"), ranges)
        self.assertIn(("2026-07-11", "2026-07-12"), ranges)
        self.assertIn(("2026-10-16", "2026-10-18"), ranges)

    def test_round_number_is_not_treated_as_day_of_month(self) -> None:
        candidates = extract_date_candidates(
            "Upcoming Round 7 Sep 11, 2026 - Sep 12, 2026 PGE Narodowy, Poland",
            default_year=2026,
        )
        ranges = {(item["start"], item["end"]) for item in candidates}
        self.assertNotIn(("2026-09-07", "2026-09-07"), ranges)
        self.assertIn(("2026-09-11", "2026-09-12"), ranges)


if __name__ == "__main__":
    unittest.main()
