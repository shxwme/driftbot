from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch

from bs4 import BeautifulSoup

from discord_notify import LOCAL_TZ, _upcoming_events
from parsers.calendars import calendar_events


class CalendarAdapterTests(unittest.TestCase):
    def test_d1_requires_season_heading_and_keeps_combined_weekend(self):
        html = (
            "<h3>2026 D1 LIGHTS SERIES</h3><figure><table><tr><td>RD.11</td>"
            "<td>12月12日(土)-13(日)</td><td>Mobara</td><td>Chiba</td></tr></table></figure>"
        )
        source = {
            "id": "d1",
            "url": "https://d1gp.co.jp",
            "parser": "d1",
            "calendar_year": 2026,
            "required_heading": "2026 D1 LIGHTS SERIES",
            "event_scope": "weekend",
        }
        soup = BeautifulSoup(html, "html.parser")
        event = calendar_events(soup, source)[0]
        self.assertEqual((event["start"], event["end"]), ("2026-12-12", "2026-12-13"))
        self.assertEqual(event["event_scope"], "weekend")
        with self.assertRaises(ValueError):
            calendar_events(soup, {**source, "required_heading": "2027 D1 LIGHTS SERIES"})

    def test_drift_kings_calendar_paragraph_excludes_story_dates(self):
        html = "<p>Round 5 &amp; Nations Cup • Serres • Greece • October 2–4 News September 7, 2026</p>"
        events = calendar_events(
            BeautifulSoup(html, "html.parser"),
            {"id": "dk", "url": "https://driftkings.com/dk26/", "parser": "drift_kings", "calendar_year": 2026},
        )
        self.assertEqual([(e["start"], e["end"]) for e in events], [("2026-10-02", "2026-10-04")])

    def test_news_and_round_numbers_do_not_become_dm_events(self):
        html = """<div class="round-card__details">
        <div class="round-card__round-number">Round 7</div>
        <div class="round-card__date">Sep 11, 2026 - Sep 12, 2026</div>
        <div class="round-card__location">PGE Narodowy, Poland</div></div>
        <aside>News September 7, 2026</aside>"""
        events = calendar_events(
            BeautifulSoup(html, "html.parser"), {"id": "dm", "parser": "drift_masters", "url": "https://dm.gp"}
        )
        self.assertEqual(
            [(e["start"], e["end"], e["label"]) for e in events], [("2026-09-11", "2026-09-12", "Runda 7")]
        )

    def test_fdj_three_divisions_stay_separate(self):
        html = """<div class="sche-box"><h3>2026 FD JAPAN SCHEDULE</h3>
        <div class="sche-txt">Rd.5 OKUIBUKI<br>September 5-6</div></div>
        <div class="sche-box2"><h3>2026 FDJ2 SCHEDULE</h3>
        <div class="sche-txt">Rd.5 MOTORPARK<br>September 12-13</div></div>
        <div class="sche-box3"><h3>2026 FDJ3 SCHEDULE</h3>
        <div class="sche-txt">Rd.4 MOTORPARK<br>September 20</div></div>"""
        for heading, expected in [
            ("2026 FD JAPAN SCHEDULE", "2026-09-05"),
            ("2026 FDJ2 SCHEDULE", "2026-09-12"),
            ("2026 FDJ3 SCHEDULE", "2026-09-20"),
        ]:
            events = calendar_events(
                BeautifulSoup(html, "html.parser"),
                {
                    "id": heading,
                    "url": "https://formulad.jp/",
                    "parser": "fdj",
                    "calendar_year": 2026,
                    "schedule_heading": heading,
                },
            )
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["start"], expected)

    @patch("discord_notify.warsaw_now", return_value=datetime(2026, 9, 5, tzinfo=LOCAL_TZ))
    def test_unverified_legacy_candidates_are_never_published(self, _now):
        current = {"date_candidates": [{"start": "2026-11-22", "end": "2026-11-22"}]}
        self.assertEqual(_upcoming_events([({"name": "D1NZ"}, current)]), [])

    @patch("discord_notify.warsaw_now", return_value=datetime(2026, 9, 5, tzinfo=LOCAL_TZ))
    def test_different_rounds_on_same_day_are_preserved(self, _now):
        current = {
            "events": [
                {"start": "2026-09-05", "end": "2026-09-05", "label": label, "verified": True}
                for label in ("Runda 7", "Runda 8")
            ]
        }
        self.assertEqual(len(_upcoming_events([({"name": "D1"}, current)])), 2)
