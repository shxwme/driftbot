from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import main
import service
from discord_notify import send_webhook
from storage import read_state, safe_error, save_state


class RuntimeTests(unittest.TestCase):
    def test_polling_sends_prealert_once_then_live_after_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "youtube.json"
            fixed_now = datetime(2026, 9, 5, 23, 36, tzinfo=UTC)
            video = {
                "id": "session",
                "title": "FDJ Top 32",
                "scheduled_start": "2026-09-05T23:45:00Z",
                "live_status": "upcoming",
            }
            with (
                patch.object(main, "STATE_PATH", path),
                patch.object(main, "load_sources", return_value=[{"id": "fdj", "type": "youtube"}]),
                patch.object(main, "datetime", wraps=datetime) as clock,
                patch.object(main, "fetch", return_value=[video]),
                patch.object(main, "send_webhook") as send,
            ):
                clock.now.return_value = fixed_now
                args = dict(
                    dry_run=False,
                    bootstrap=True,
                    no_notify=False,
                    test_notification=False,
                    digest_notification=False,
                    source_type="youtube",
                )
                main.run(**args)
                main.run(**args)
                self.assertEqual(send.call_count, 1)
                self.assertIn("START ZA CHWILĘ", str(send.call_args))
                video["live_status"] = "live"
                main.run(**args)
                main.run(**args)
                self.assertEqual(send.call_count, 2)
                self.assertIn("LIVE TERAZ", str(send.call_args))

    @patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://example.com/private-token"})
    def test_webhook_requests_confirmed_delivery_and_link_components(self):
        with patch("discord_notify.requests.post") as post:
            post.return_value.status_code = 200
            post.return_value.ok = True
            send_webhook({"content": "test"})
            self.assertEqual(post.call_args.kwargs["params"], {"wait": "true", "with_components": "true"})
            self.assertEqual(post.call_args.kwargs["json"]["allowed_mentions"], {"parse": []})

    def test_worker_failure_is_visible_and_state_files_are_separate(self):
        with patch("service.subprocess.run") as run:
            run.return_value.returncode = 1
            self.assertFalse(service.worker("youtube", 300, True, True))
            self.assertTrue(run.call_args.kwargs["env"]["DRIFT_STATE_PATH"].endswith("youtube.json"))
            self.assertEqual(run.call_args.kwargs["timeout"], 240)
            run.return_value.returncode = 0
            self.assertTrue(service.worker("calendar", 28800, True, True))
            self.assertTrue(run.call_args.kwargs["env"]["DRIFT_STATE_PATH"].endswith("calendar.json"))

    @patch("discord_notify.warsaw_now", return_value=datetime(2026, 9, 5, tzinfo=UTC))
    def test_calendar_state_survives_restart_and_transport_failure(self, _now):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "calendar.json"
            today = "2026-09-05"
            source = {"id": "test", "name": "test", "type": "html", "url": "https://example.com"}
            current = {"events": [{"start": today, "end": today, "label": "Runda 1", "verified": True}]}
            with (
                patch.object(main, "STATE_PATH", path),
                patch.object(main, "load_sources", return_value=[source]),
                patch.object(main, "fetch", return_value=current),
                patch.object(main, "send_webhook", side_effect=RuntimeError("network")),
            ):
                with self.assertRaises(RuntimeError):
                    main.run(
                        dry_run=False,
                        bootstrap=False,
                        no_notify=False,
                        test_notification=False,
                        digest_notification=False,
                        source_type="calendar",
                    )
            saved = read_state(path)
            self.assertEqual(saved["sources"]["test"], current)
            self.assertIn("pending_calendar_notification", saved)

    def test_finished_video_near_scheduled_time_does_not_send_alert(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "youtube.json"
            now = datetime.now(UTC)
            video = {
                "id": "finished",
                "scheduled_start": (now - timedelta(minutes=5)).isoformat(),
                "actual_end": now.isoformat(),
                "live_status": "none",
            }
            with (
                patch.object(main, "STATE_PATH", path),
                patch.object(main, "load_sources", return_value=[{"id": "yt", "type": "youtube"}]),
                patch.object(main, "fetch", return_value=[video]),
                patch.object(main, "send_webhook") as send,
            ):
                main.run(
                    dry_run=False,
                    bootstrap=True,
                    no_notify=False,
                    test_notification=False,
                    digest_notification=False,
                    source_type="youtube",
                )
            send.assert_not_called()

    @patch.dict(os.environ, {"YOUTUBE_API_KEY": "test-key"})
    def test_tracked_live_video_is_polled_after_leaving_upload_playlist(self):
        response = Mock()
        response.json.return_value = {"items": [{"snippet": {"resourceId": {"videoId": "new-video"}}}]}
        detail = Mock()
        detail.json.return_value = {"items": []}
        source = {"uploads_playlist_id": "uploads", "tracked_video_ids": ["scheduled-video"]}
        with patch("main.requests.get", side_effect=[response, detail]) as get:
            main.fetch_youtube(source)
        self.assertEqual(get.call_args_list[1].kwargs["params"]["id"], "scheduled-video,new-video")
        self.assertEqual(source["_quota"]["used"], 2)

    def test_atomic_save_and_redacted_exceptions(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            save_state(path, {"value": 1})
            save_state(path, {"value": 2})
            self.assertEqual(read_state(path), {"value": 2})
            self.assertEqual([p.name for p in Path(folder).iterdir()], ["state.json"])
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "private-key"}):
            self.assertNotIn("private-key", safe_error(RuntimeError("URL ?key=private-key")))
