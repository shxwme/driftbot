import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from discord_notify import LOCAL_TZ, format_upcoming_digest
from main import load_sources


class OutputContractTests(unittest.TestCase):
    @patch("discord_notify.warsaw_now", return_value=datetime(2026, 9, 5, tzinfo=LOCAL_TZ))
    def test_large_digest_fits_discord_limits(self, _now):
        events = []
        for index in range(40):
            day = (datetime(2026, 9, 5) + timedelta(days=index)).date().isoformat()
            source = {"name": "Series " + "x" * 200, "url": "https://example.com"}
            events.append(
                (source, {"events": [{"start": day, "end": day, "label": "Round " + "y" * 400, "verified": True}]})
            )
        embed = format_upcoming_digest(events)["embeds"][0]
        count = len(embed["title"]) + len(embed["description"]) + len(embed["footer"]["text"])
        for field in embed["fields"]:
            self.assertLessEqual(len(field["name"]), 256)
            self.assertLessEqual(len(field["value"]), 1024)
            count += len(field["name"]) + len(field["value"])
        self.assertLessEqual(count, 6000)
        self.assertLessEqual(len(embed["fields"]), 25)

    def test_source_ids_are_unique_and_parser_years_explicit(self):
        sources = load_sources()
        self.assertEqual(len(sources), len({s["id"] for s in sources}))
        for source in sources:
            if source.get("parser"):
                self.assertIsInstance(source["calendar_year"], int)
