from __future__ import annotations

import unittest

from parsers.generic import extract_date_candidates


class DateParserTests(unittest.TestCase):
    def test_european_cross_month_and_spaced_ranges(self):
        cases = {
            "07. 08. - 08. 08. 2026": ("2026-08-07", "2026-08-08"),
            "31.7.-1.8.2026": ("2026-07-31", "2026-08-01"),
            "23.-24.5.2026": ("2026-05-23", "2026-05-24"),
            "09/05/2026 - 10/05/2026": ("2026-05-09", "2026-05-10"),
            "2026年12月12日(土)-13(日)": ("2026-12-12", "2026-12-13"),
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual([(c["start"], c["end"]) for c in extract_date_candidates(raw)], [expected])

    def test_explicit_year_wins_over_season_heading(self) -> None:
        candidates = extract_date_candidates("2026 D1NZ CALENDAR 21-22 November 2025")
        self.assertEqual([(c["start"], c["end"]) for c in candidates], [("2025-11-21", "2025-11-22")])

    def test_japanese_same_month_range(self) -> None:
        candidates = extract_date_candidates("2026年9月5日(土)～6日(日)")
        self.assertEqual([(c["start"], c["end"]) for c in candidates], [("2026-09-05", "2026-09-06")])

    def test_ambiguous_year_is_not_guessed(self) -> None:
        self.assertEqual(extract_date_candidates("Season 2025 archive 2026 September 5-6"), [])

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
