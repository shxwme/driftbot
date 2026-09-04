"""Small WSGI control plane for Render Free; the cron never sends arbitrary jobs."""

from __future__ import annotations

import hmac
import json
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from cloud_store import rpc
from storage import safe_error

ROOT = Path(__file__).resolve().parent
JOBS = {"youtube": (240, 240), "calendar": (480, 60), "digest": (90, 240)}
REQUIRED = ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "CRON_SECRET", "YOUTUBE_API_KEY", "DISCORD_WEBHOOK_URL")


def configured() -> bool:
    return all(os.environ.get(key) for key in REQUIRED) and len(os.environ.get("CRON_SECRET", "")) >= 32


def execute(kind: str, token: str) -> None:
    ok = False
    try:
        env = {**os.environ, "DRIFT_REMOTE_STATE_KEY": kind, "DRIFT_JOB_TOKEN": token}
        env.pop("DRIFT_SOURCE_ID", None)
        result = subprocess.run(
            [sys.executable, str(ROOT / "cloud_job.py"), kind], cwd=ROOT, env=env, timeout=JOBS[kind][0], check=False
        )
        ok = result.returncode == 0
    except Exception as exc:
        print(f"Cloud job {kind}: {safe_error(exc)}", flush=True)
    finally:
        try:
            rpc("finish", {"p_name": kind, "p_token": token, "p_ok": ok})
        except Exception as exc:
            print(f"Job completion persistence: {safe_error(exc)}", flush=True)


def application(environ, start_response):
    def reply(code: str, payload: dict):
        body = json.dumps(payload).encode()
        start_response(
            code,
            [("Content-Type", "application/json"), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")],
        )
        return [body]

    path = environ.get("PATH_INFO", "")
    if path == "/healthz":
        return reply("200 OK" if configured() else "503 Service Unavailable", {"ready": configured()})
    if not configured():
        return reply("503 Service Unavailable", {"error": "configuration_required"})
    expected = f"Bearer {os.environ['CRON_SECRET']}"
    if not hmac.compare_digest(environ.get("HTTP_AUTHORIZATION", ""), expected):
        return reply("401 Unauthorized", {"error": "unauthorized"})
    try:
        if path == "/status" and environ.get("REQUEST_METHOD") == "GET":
            return reply("200 OK", {"jobs": rpc("status")})
        kind = path.removeprefix("/jobs/") if path.startswith("/jobs/") else ""
        if kind not in JOBS:
            return reply("404 Not Found", {"error": "not_found"})
        if environ.get("REQUEST_METHOD") != "POST":
            return reply("405 Method Not Allowed", {"error": "use_post"})
        token = str(uuid.uuid4())
        timeout, interval = JOBS[kind]
        acquired = rpc("claim", {"p_name": kind, "p_token": token, "p_seconds": timeout + 90, "p_interval": interval})
        if not acquired:
            return reply("200 OK", {"status": "running_or_recently_checked", "job": kind})
        try:
            threading.Thread(target=execute, args=(kind, token), daemon=True, name=f"drift-{kind}").start()
        except Exception:
            rpc("finish", {"p_name": kind, "p_token": token, "p_ok": False})
            raise
        # Accepted is not completed: /status exposes durable completion results.
        return reply("202 Accepted", {"status": "accepted", "job": kind})
    except Exception as exc:
        print(safe_error(exc), flush=True)
        return reply("503 Service Unavailable", {"error": "backend_unavailable"})


if __name__ == "__main__":
    from waitress import serve

    serve(application, host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threads=4)
