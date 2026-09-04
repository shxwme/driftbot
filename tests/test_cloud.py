from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import cloud_job
import cloud_store
import cloud_web
import storage

ENV = {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_SECRET_KEY": "sb_secret_test",
    "CRON_SECRET": "x" * 40,
    "YOUTUBE_API_KEY": "test",
    "DISCORD_WEBHOOK_URL": "https://example.com",
}


@patch.dict(os.environ, ENV)
class CloudTests(unittest.TestCase):
    def request(self, path, method="POST", auth=True):
        status = []
        env = {"PATH_INFO": path, "REQUEST_METHOD": method}
        if auth:
            env["HTTP_AUTHORIZATION"] = "Bearer " + ENV["CRON_SECRET"]
        body = cloud_web.application(env, lambda code, _headers: status.append(code))
        return status[0], json.loads(b"".join(body))

    def test_unauthenticated_requests_never_reach_database_or_spawn(self):
        with patch("cloud_web.rpc") as rpc, patch("cloud_web.threading.Thread") as thread:
            self.assertEqual(self.request("/jobs/youtube", auth=False)[0], "401 Unauthorized")
            rpc.assert_not_called()
            thread.assert_not_called()

    def test_post_accepts_only_after_durable_claim_and_returns_without_waiting(self):
        with patch("cloud_web.rpc", return_value=True) as rpc, patch("cloud_web.threading.Thread") as thread:
            code, payload = self.request("/jobs/youtube")
            self.assertEqual(code, "202 Accepted")
            self.assertEqual(payload["status"], "accepted")
            self.assertEqual(rpc.call_args.args[0], "claim")
            self.assertEqual(rpc.call_args.args[1]["p_seconds"], 330)
            thread.return_value.start.assert_called_once()

    def test_duplicate_or_recent_job_does_not_spawn(self):
        with patch("cloud_web.rpc", return_value=False), patch("cloud_web.threading.Thread") as thread:
            self.assertEqual(self.request("/jobs/calendar")[0], "200 OK")
            thread.assert_not_called()

    def test_get_and_arbitrary_jobs_cannot_execute(self):
        with patch("cloud_web.rpc") as rpc:
            self.assertEqual(self.request("/jobs/youtube", method="GET")[0], "405 Method Not Allowed")
            self.assertEqual(self.request("/jobs/arbitrary")[0], "404 Not Found")
            rpc.assert_not_called()

    def test_database_outage_is_not_success_or_local_fallback(self):
        with patch("cloud_web.rpc", side_effect=RuntimeError("offline")), patch("cloud_web.threading.Thread") as thread:
            self.assertEqual(self.request("/jobs/youtube")[0], "503 Service Unavailable")
            thread.assert_not_called()
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.dict(os.environ, {"DRIFT_REMOTE_STATE_KEY": "youtube", "DRIFT_JOB_TOKEN": "token"}),
            patch("cloud_store.rpc", return_value=False),
        ):
            path = Path(folder) / "state.json"
            with self.assertRaisesRegex(RuntimeError, "lease expired"):
                storage.save_state(path, {"sources": {}})
            self.assertFalse(path.exists())

    def test_job_timeout_records_failure(self):
        with patch("cloud_web.subprocess.run", side_effect=TimeoutError("timeout")), patch("cloud_web.rpc") as rpc:
            cloud_web.execute("calendar", "owner")
            self.assertEqual(rpc.call_args.args, ("finish", {"p_name": "calendar", "p_token": "owner", "p_ok": False}))

    def test_new_supabase_key_not_used_as_jwt(self):
        response = Mock(ok=True)
        response.json.return_value = {}
        with patch("cloud_store.requests.post", return_value=response) as post:
            cloud_store.read_remote("youtube")
            self.assertNotIn("Authorization", post.call_args.kwargs["headers"])
            self.assertEqual(post.call_args.kwargs["headers"]["apikey"], "sb_secret_test")

    def test_supabase_host_is_validated_before_transmitting_key(self):
        with (
            patch.dict(os.environ, {"SUPABASE_URL": "https://evil.example"}),
            patch("cloud_store.requests.post") as post,
        ):
            with self.assertRaises(RuntimeError):
                cloud_store.read_remote("youtube")
            post.assert_not_called()

    def test_calendar_selects_oldest_due_and_skips_recent_sources(self):
        now = datetime(2026, 9, 5, tzinfo=UTC)
        sources = [{"id": "new", "type": "html"}, {"id": "old", "type": "html"}, {"id": "yt", "type": "youtube"}]
        state = {
            "source_health": {
                "new": {"ok": True, "checked_at": now.isoformat()},
                "old": {"ok": True, "checked_at": (now - timedelta(hours=9)).isoformat()},
            }
        }
        self.assertEqual(cloud_job.calendar_source(state, sources, now), "old")
        state["source_health"]["old"]["checked_at"] = now.isoformat()
        self.assertIsNone(cloud_job.calendar_source(state, sources, now))

    @patch("cloud_job.warsaw_now", return_value=datetime(2026, 9, 5, 9, tzinfo=UTC))
    def test_digest_slot_survives_restart(self, _now):
        with (
            patch.dict(os.environ, {"DRIFT_REMOTE_STATE_KEY": "digest", "DRIFT_JOB_TOKEN": "owner"}),
            patch("cloud_job.read_remote", return_value={"last_slot": "2026-09-05:9"}),
            patch("cloud_job.send_webhook") as send,
        ):
            self.assertEqual(cloud_job.digest(), 0)
            send.assert_not_called()

    def test_health_reveals_no_secrets_and_missing_config_is_not_ready(self):
        code, payload = self.request("/healthz", method="GET", auth=False)
        self.assertEqual(code, "200 OK")
        self.assertEqual(payload, {"ready": True})
        with patch.dict(os.environ, {"CRON_SECRET": ""}):
            self.assertEqual(self.request("/healthz", method="GET", auth=False)[0], "503 Service Unavailable")
