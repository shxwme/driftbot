"""Supabase RPC storage with fenced leases; no local fallback after a DB failure."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

import requests


def rpc(operation: str, payload: dict | None = None) -> Any:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SECRET_KEY", "")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or not parts.hostname.endswith(".supabase.co"):
        raise RuntimeError("SUPABASE_URL must be the HTTPS project API URL")
    if not key:
        raise RuntimeError("SUPABASE_SECRET_KEY is not configured")
    headers = {"apikey": key, "Content-Type": "application/json"}
    # New sb_secret keys belong only in apikey, not in a JWT Authorization header.
    if not key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {key}"
    try:
        response = requests.post(
            f"{url}/rest/v1/rpc/drift_{operation}", headers=headers, json=payload or {}, timeout=12
        )
    except requests.RequestException:
        raise RuntimeError("Supabase connection failed") from None
    if not response.ok:
        raise RuntimeError(f"Supabase {operation} failed: HTTP {response.status_code}")
    return response.json()


def read_remote(name: str) -> dict:
    result = rpc("read", {"p_name": name})
    if not isinstance(result, dict):
        raise RuntimeError("Invalid Supabase state response")
    return result


def write_remote(name: str, token: str, value: dict) -> None:
    if not rpc("write", {"p_name": name, "p_token": token, "p_value": value}):
        raise RuntimeError("Job lease expired; state write refused")


def assert_lease() -> None:
    name = os.environ.get("DRIFT_REMOTE_STATE_KEY")
    if name and not rpc("owned", {"p_name": name, "p_token": os.environ["DRIFT_JOB_TOKEN"]}):
        raise RuntimeError("Job lease expired; notification refused")
