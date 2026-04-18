from __future__ import annotations

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
    activity_to_row,
    refresh_access_token,
    upload_tcx,
)
from app.suggestions import suggest_pairs
from app.tokens import clear_tokens, is_configured, load_tokens

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Strava Merge", version="1.0.0")


@app.on_event("startup")
def _startup():
    settings.data_dir.mkdir(parents=True, exist_ok=True)


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class MergeRequest(BaseModel):
    activity_ids: list[int] = Field(..., min_length=2, max_length=2)
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""


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
    try:
        client = ensure_client(settings)
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    tmp: str | None = None
    try:
        tmp = merge_to_tempfile(client, ids[0], ids[1])
        access = _bearer()
        result = upload_tcx(
            access,
            tmp,
            name=body.name.strip(),
            description=body.description.strip(),
        )
        return {"ok": True, "upload": result}
    except Exception as e:
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


@app.get("/")
def index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.is_file():
        return JSONResponse(
            {"error": "Brak static/index.html — zbuduj frontend lub skopiuj pliki."},
            status_code=503,
        )
    return FileResponse(index_path)
