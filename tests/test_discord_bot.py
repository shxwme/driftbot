from __future__ import annotations

import os
import unittest
from datetime import date
from unittest.mock import patch

import discord_bot


class DiscordBotTests(unittest.TestCase):
    def test_slash_commands_include_help(self):
        self.assertEqual(
            {command.name for command in discord_bot.bot.tree.get_commands()},
            {"next", "today", "series", "help"},
        )

    def test_filters_youtube_events_by_polish_day(self):
        source = {"id": "d1", "name": "D1GP"}
        videos = [
            {"id": "night", "scheduled_start": "2026-09-05T21:35:00Z"},
            {"id": "morning", "scheduled_start": "2026-09-06T00:35:00Z"},
        ]
        filtered = discord_bot._filter_for_day([(source, videos)], date(2026, 9, 6))
        self.assertEqual([video["id"] for video in filtered[0][1]], ["morning"])

    def test_filter_series_is_case_insensitive(self):
        observations = [({"id": "dm", "name": "Drift Masters"}, {}), ({"id": "d1", "name": "D1GP"}, {})]
        self.assertEqual(len(discord_bot._filter_for_series(observations, "drift")), 1)

    @patch.dict(os.environ, {}, clear=True)
    def test_bot_is_optional_without_token(self):
        self.assertIsNone(discord_bot.start_bot())
