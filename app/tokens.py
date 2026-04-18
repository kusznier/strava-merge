import json
import threading
import time
from pathlib import Path
from typing import Any

_lock = threading.Lock()


def _path(data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "strava_tokens.json"


def load_tokens(data_dir: Path) -> dict[str, Any] | None:
    p = _path(data_dir)
    if not p.is_file():
        return None
    with _lock:
        with open(p, encoding="utf-8") as f:
            return json.load(f)


def save_tokens(data_dir: Path, payload: dict[str, Any]) -> None:
    p = _path(data_dir)
    with _lock:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        tmp.replace(p)


def clear_tokens(data_dir: Path) -> None:
    p = _path(data_dir)
    with _lock:
        if p.is_file():
            p.unlink()


def access_token_fresh(data_dir: Path) -> tuple[str | None, int]:
    """Returns (access_token or None, expires_at epoch seconds)."""
    raw = load_tokens(data_dir)
    if not raw:
        return None, 0
    return raw.get("access_token"), int(raw.get("expires_at") or 0)


def is_configured(settings) -> bool:
    return bool(settings.strava_client_id and settings.strava_client_secret)


def token_needs_refresh(expires_at: int, skew_seconds: int = 120) -> bool:
    return time.time() >= (expires_at - skew_seconds)
