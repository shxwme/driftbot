from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch

from discord_notify import LOCAL_TZ, format_change, format_live_alert, format_upcoming_digest
from main import live_notification_key


class NotificationTests(unittest.TestCase):
    def test_pre_alert_does_not_block_live_alert(self) -> None:
        scheduled = "2026-09-05T23:45:00Z"
        pre = live_notification_key("fd", "video", scheduled, is_live=False)
        live = live_notification_key("fd", "video", scheduled, is_live=True)
        self.assertNotEqual(pre, live)

    def test_live_alert_converts_utc_to_warsaw_and_marks_overnight(self) -> None:
        payload = format_live_alert(
            "Formula DRIFT YouTube",
            {
                "id": "example",
                "title": "FDJ Round 5 — Top 32",
                "scheduled_start": "2026-09-05T23:45:00Z",
                "live_status": "upcoming",
            },
            10,
        )
        rendered = str(payload)
        self.assertIn("06.09.2026 · 01:45", rendered)
        self.assertIn("NOC Z 05.09 NA 06.09", rendered)
        self.assertIn("https://www.youtube.com/watch?v=example", rendered)

    @patch("discord_notify.warsaw_now", return_value=datetime(2026, 8, 29, 20, 0, tzinfo=LOCAL_TZ))
    def test_digest_excludes_finished_streams_and_highlights_tonight(self, _mock_now) -> None:
        source = {"id": "d1gp-youtube", "name": "D1GP YouTube", "type": "youtube"}
        videos = [
            {
                "id": "finished",
                "title": "Finished",
                "scheduled_start": "2026-08-29T10:00:00Z",
                "actual_end": "2026-08-29T12:00:00Z",
                "live_status": "none",
            },
            {
                "id": "tonight",
                "title": "D1 Lights Rd.8",
                "scheduled_start": "2026-08-30T00:35:00Z",
                "actual_end": None,
                "live_status": "upcoming",
            },
        ]
        rendered = str(format_upcoming_digest([(source, videos)]))
        self.assertNotIn("Finished", rendered)
        self.assertIn("D1 Lights Rd.8", rendered)
        self.assertIn("02:35", rendered)
        self.assertIn("NOC Z 29.08 NA 30.08", rendered)

    def test_change_notification_is_an_embed_with_source_links(self) -> None:
        source = {
            "id": "dmp-calendar",
            "name": "DMP",
            "url": "https://example.com/calendar",
            "watch_url": "https://youtube.com/example",
        }
        after = {
            "date_candidates": [{"raw": "30.08.2026", "start": "2026-08-30", "end": "2026-08-30"}],
            "items": ["RND 1 30.08.2026"],
        }
        payload = format_change(source, {}, after)
        self.assertIn("embeds", payload)
        self.assertNotIn("Poprzedni odczyt", str(payload))
        self.assertIn("https://youtube.com/example", str(payload))


if __name__ == "__main__":
    unittest.main()
