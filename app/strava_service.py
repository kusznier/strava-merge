from __future__ import annotations

import time
from typing import Any

import requests
from stravalib import Client

from app.config import Settings
from app.tokens import load_tokens, save_tokens, token_needs_refresh


def refresh_access_token(settings: Settings) -> dict[str, Any]:
    raw = load_tokens(settings.data_dir)
    if not raw or not raw.get("refresh_token"):
        raise RuntimeError("Brak refresh tokena — zaloguj się ponownie przez Strava.")
    r = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": settings.strava_client_id,
            "client_secret": settings.strava_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": raw["refresh_token"],
        },
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    payload = {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", raw["refresh_token"]),
        "expires_at": int(data.get("expires_at", 0)),
        "athlete_id": raw.get("athlete_id"),
    }
    save_tokens(settings.data_dir, payload)
    return payload


def ensure_client(settings: Settings) -> Client:
    raw = load_tokens(settings.data_dir)
    if not raw:
        raise RuntimeError("Nie zalogowano — użyj Połącz ze Strava.")
    expires_at = int(raw.get("expires_at") or 0)
    if token_needs_refresh(expires_at):
        refresh_access_token(settings)
        raw = load_tokens(settings.data_dir)
    return Client(
        access_token=raw["access_token"],
        refresh_token=raw.get("refresh_token"),
        token_expires=int(raw.get("expires_at") or 0),
    )


def exchange_code(settings: Settings, code: str) -> dict[str, Any]:
    r = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": settings.strava_client_id,
            "client_secret": settings.strava_client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": settings.redirect_uri,
        },
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    athlete = data.get("athlete") or {}
    payload = {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", ""),
        "expires_at": int(data.get("expires_at", 0)),
        "athlete_id": athlete.get("id"),
    }
    save_tokens(settings.data_dir, payload)
    return payload


def auth_url(settings: Settings) -> str:
    from urllib.parse import urlencode

    q = urlencode(
        {
            "client_id": settings.strava_client_id,
            "redirect_uri": settings.redirect_uri,
            "response_type": "code",
            "approval_prompt": "auto",
            "scope": "activity:read,activity:write",
        }
    )
    return f"https://www.strava.com/oauth/authorize?{q}"


def fetch_activities_pages(
    access_token: str,
    *,
    after_ts: int | None = None,
    before_ts: int | None = None,
    max_pages: int = 20,
) -> list[dict[str, Any]]:
    """Pobiera listę aktywności ze Strava API (surowy JSON)."""
    out: list[dict[str, Any]] = []
    headers = {"Authorization": f"Bearer {access_token}"}
    for page in range(1, max_pages + 1):
        params: dict[str, Any] = {"page": page, "per_page": 200}
        if after_ts is not None:
            params["after"] = after_ts
        if before_ts is not None:
            params["before"] = before_ts
        r = requests.get(
            "https://www.strava.com/api/v3/athlete/activities",
            headers=headers,
            params=params,
            timeout=60,
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 200:
            break
    return out


def activity_to_row(a: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": a["id"],
        "name": a.get("name") or "",
        "type": a.get("type") or a.get("sport_type") or "",
        "start_date": a.get("start_date"),
        "elapsed_time": int(a.get("elapsed_time") or 0),
        "distance": float(a.get("distance") or 0),
    }


def upload_tcx(
    access_token: str,
    file_path: str,
    *,
    name: str,
    description: str = "",
) -> dict[str, Any]:
    url = "https://www.strava.com/api/v3/uploads"
    headers = {"Authorization": f"Bearer {access_token}"}
    data = {
        "name": name,
        "description": description,
        "trainer": "false",
        "commute": "false",
        "data_type": "tcx",
    }
    with open(file_path, "rb") as f:
        files = {"file": ("merged.tcx", f, "application/tcx+xml")}
        r = requests.post(url, headers=headers, data=data, files=files, timeout=120)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Upload failed: {r.status_code} {r.text}")
    return r.json()
