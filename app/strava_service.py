from __future__ import annotations

import logging
import time
from typing import Any

import requests
from stravalib import Client

from app.config import Settings
from app.tokens import load_tokens, save_tokens, token_needs_refresh

logger = logging.getLogger(__name__)


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
        # Often empty on list endpoint; use GET /api/activity/{id} for device_name.
        "device_name": a.get("device_name") or "",
    }


def fetch_activity_detail(access_token: str, activity_id: int) -> dict[str, Any]:
    """GET /activities/{id} — includes device_name, gear, etc."""
    r = requests.get(
        f"https://www.strava.com/api/v3/activities/{activity_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=60,
    )
    r.raise_for_status()
    raw = r.json()
    return {
        "id": raw["id"],
        "name": raw.get("name") or "",
        "type": raw.get("type") or raw.get("sport_type") or "",
        "sport_type": raw.get("sport_type") or "",
        "device_name": raw.get("device_name") or "",
        "gear_id": raw.get("gear_id"),
        "start_date": raw.get("start_date"),
        "elapsed_time": int(raw.get("elapsed_time") or 0),
        "distance": float(raw.get("distance") or 0),
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
    out = r.json()
    logger.info(
        "strava upload accepted: id=%s status=%s activity_id=%s error=%s",
        out.get("id"),
        out.get("status"),
        out.get("activity_id"),
        out.get("error"),
    )
    return out


def delete_activity(access_token: str, activity_id: int) -> None:
    r = requests.delete(
        f"https://www.strava.com/api/v3/activities/{activity_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=60,
    )
    if r.status_code not in (200, 204):
        raise RuntimeError(f"Delete activity {activity_id} failed: {r.status_code} {r.text}")


def fetch_upload_status(access_token: str, upload_id: int) -> dict[str, Any]:
    """Poll Strava processing status for a file upload (GET /uploads/{id})."""
    url = f"https://www.strava.com/api/v3/uploads/{upload_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(url, headers=headers, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Upload status failed: {r.status_code} {r.text}")
    return r.json()
