from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import Settings, settings
from app.merge_service import merge_to_tempfile
from app.strava_service import (
    auth_url,
    ensure_client,
    exchange_code,
    fetch_activities_pages,
    fetch_activity_detail,
    fetch_upload_status,
    activity_to_row,
    refresh_access_token,
    upload_tcx,
)
from app.suggestions import suggest_pairs
from app.tokens import clear_tokens, is_configured, load_tokens

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

logger = logging.getLogger(__name__)

app = FastAPI(title="Strava Merge", version="1.0.0")


@app.on_event("startup")
def _startup():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    try:
        logging.basicConfig(level=logging.INFO, format=fmt, force=True)
    except TypeError:
        logging.basicConfig(level=logging.INFO, format=fmt)


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class MergeRequest(BaseModel):
    activity_ids: list[int] = Field(..., min_length=2, max_length=2)
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    # Which activity defines TCX <Activity Sport="..."> (e.g. head unit vs watch). Must be one of activity_ids.
    primary_activity_id: int | None = None


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def api_config():
    """Co frontend musi wiedzieć bez sekretów."""
    return {
        "configured": is_configured(settings),
        "redirect_uri": settings.redirect_uri,
        "public_base_url": settings.public_base_url,
    }


@app.get("/api/auth/status")
def auth_status():
    raw = load_tokens(settings.data_dir)
    if not raw:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "expires_at": raw.get("expires_at"),
        "athlete_id": raw.get("athlete_id"),
    }


@app.get("/api/auth/login")
def auth_login():
    if not is_configured(settings):
        raise HTTPException(
            status_code=503,
            detail="Brak STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET w środowisku.",
        )
    return RedirectResponse(auth_url(settings), status_code=302)


@app.get("/api/auth/callback")
def auth_callback(
    code: str | None = None,
    error: str | None = None,
    scope: str | None = None,
):
    if error:
        return RedirectResponse(f"/?error={error}", status_code=302)
    if not code:
        return RedirectResponse("/?error=missing_code", status_code=302)
    try:
        exchange_code(settings, code)
    except Exception as e:
        return RedirectResponse(f"/?error=token_exchange&message={e!s}", status_code=302)
    return RedirectResponse("/?connected=1", status_code=302)


@app.post("/api/auth/logout")
def auth_logout():
    clear_tokens(settings.data_dir)
    return {"ok": True}


def _bearer() -> str:
    raw = load_tokens(settings.data_dir)
    if not raw:
        raise HTTPException(status_code=401, detail="Nie zalogowano.")
    expires_at = int(raw.get("expires_at") or 0)
    from app.tokens import token_needs_refresh

    if token_needs_refresh(expires_at):
        try:
            refresh_access_token(settings)
            raw = load_tokens(settings.data_dir)
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Odświeżenie tokena nie powiodło się: {e}") from e
    return raw["access_token"]


@app.get("/api/activities")
def list_activities(days: int = Query(90, ge=1, le=365)):
    after_ts = int(time.time()) - days * 86400
    access = _bearer()
    raw_list = fetch_activities_pages(
        access,
        after_ts=after_ts,
        max_pages=settings.max_activity_pages,
    )
    rows = [activity_to_row(a) for a in raw_list]
    rows.sort(key=lambda r: r.get("start_date") or "", reverse=True)
    return {"activities": rows, "count": len(rows)}


@app.get("/api/activity/{activity_id}")
def activity_detail(activity_id: int):
    """Single activity details from Strava (includes device_name when available)."""
    access = _bearer()
    return fetch_activity_detail(access, activity_id)


@app.get("/api/suggestions")
def list_suggestions(days: int = Query(60, ge=1, le=180)):
    after_ts = int(time.time()) - days * 86400
    access = _bearer()
    raw_list = fetch_activities_pages(
        access,
        after_ts=after_ts,
        max_pages=settings.max_activity_pages,
    )
    rows = [activity_to_row(a) for a in raw_list]
    pairs = suggest_pairs(rows)
    return {"pairs": pairs}


@app.post("/api/merge")
def merge_activities(body: MergeRequest):
    ids = body.activity_ids
    if ids[0] == ids[1]:
        raise HTTPException(status_code=400, detail="Wybierz dwie różne aktywności.")
    if body.primary_activity_id is not None and body.primary_activity_id not in (ids[0], ids[1]):
        raise HTTPException(
            status_code=400,
            detail="primary_activity_id must be one of the two activity ids.",
        )
    try:
        client = ensure_client(settings)
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    logger.info(
        "merge start activity_ids=%s primary_activity_id=%s name=%r",
        ids,
        body.primary_activity_id,
        body.name.strip(),
    )
    tmp: str | None = None
    try:
        tmp = merge_to_tempfile(
            client,
            ids[0],
            ids[1],
            primary_activity_id=body.primary_activity_id,
        )
        access = _bearer()
        result = upload_tcx(
            access,
            tmp,
            name=body.name.strip(),
            description=body.description.strip(),
        )
        logger.info("merge done upload_id=%s", result.get("id"))
        return {"ok": True, "upload": result}
    except Exception as e:
        logger.exception("merge failed: %s", e)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(e)},
        )
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


@app.get("/api/uploads/{upload_id}")
def upload_status(upload_id: int):
    """Strava upload queue status (processing / error / activity_id when ready)."""
    access = _bearer()
    try:
        return fetch_upload_status(access, upload_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.get("/")
def index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.is_file():
        return JSONResponse(
            {"error": "Brak static/index.html — zbuduj frontend lub skopiuj pliki."},
            status_code=503,
        )
    return FileResponse(index_path)
