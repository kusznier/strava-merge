"""Backup aktywności na dysk (DATA_DIR/backups)."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from app.strava_service import fetch_activities_pages

logger = logging.getLogger(__name__)


def _backups_root(data_dir: Path) -> Path:
    p = data_dir / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_all_activities_snapshot(
    access_token: str,
    data_dir: Path,
    *,
    max_pages: int,
) -> tuple[Path, int]:
    """Pełna lista z /athlete/activities (wszystkie strony, bez filtra czasu)."""
    raw = fetch_activities_pages(access_token, after_ts=None, max_pages=max_pages)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = _backups_root(data_dir) / f"activities_snapshot_{ts}.json"
    payload = {
        "saved_at_utc": ts,
        "count": len(raw),
        "activities": raw,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    logger.info("snapshot: wrote %s count=%s", path, len(raw))
    return path, len(raw)


def fetch_activity_raw(access_token: str, activity_id: int) -> dict[str, Any]:
    r = requests.get(
        f"https://www.strava.com/api/v3/activities/{activity_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


def fetch_activity_streams_raw(access_token: str, activity_id: int) -> Any:
    r = requests.get(
        f"https://www.strava.com/api/v3/activities/{activity_id}/streams",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "keys": "time,latlng,distance,altitude,heartrate,cadence,watts",
            "key_by_type": "true",
        },
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


def backup_two_activities(
    access_token: str,
    data_dir: Path,
    id_a: int,
    id_b: int,
) -> Path:
    """Zapisuje szczegóły + streamy dwóch aktywności przed usunięciem."""
    folder = _backups_root(data_dir) / f"pair_{id_a}_{id_b}_{uuid.uuid4().hex[:10]}"
    folder.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "activity_ids": [id_a, id_b],
        "files": [],
    }
    for aid in (id_a, id_b):
        detail = fetch_activity_raw(access_token, aid)
        p1 = folder / f"activity_{aid}_detail.json"
        with open(p1, "w", encoding="utf-8") as f:
            json.dump(detail, f, indent=2, ensure_ascii=False)
        manifest["files"].append(str(p1.name))
        try:
            streams = fetch_activity_streams_raw(access_token, aid)
            p2 = folder / f"activity_{aid}_streams.json"
            with open(p2, "w", encoding="utf-8") as f:
                json.dump(streams, f, indent=2, ensure_ascii=False)
            manifest["files"].append(str(p2.name))
        except Exception as e:
            logger.warning("streams backup failed for %s: %s", aid, e)
            manifest[f"streams_error_{aid}"] = str(e)
    with open(folder / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    logger.info("pair backup: %s", folder)
    return folder
