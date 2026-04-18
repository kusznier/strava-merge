# Strava Merge (web + Docker)

A small web app for Strava OAuth with **persistent tokens** (access + refresh), an activity list, **pair suggestions** for overlapping or close-in-time activities (e.g. watch + head unit), merging two activities into one TCX, and uploading the result to Strava.

## Contents

- [Requirements](#requirements)
- [Strava API app and OAuth](#strava-api-app-and-oauth)
- [Environment variables](#environment-variables)
- [Run with Docker / Compose](#run-with-docker--compose)
- [Unraid](#unraid)
- [Local development](#local-development)
- [HTTP API](#http-api)
- [Logs and upload status](#logs-and-upload-status)
- [Merging back-to-back activities](#merging-back-to-back-activities)
- [Why the CLI kept asking for auth](#why-the-cli-kept-asking-for-auth)
- [Troubleshooting](#troubleshooting)
- [Further documentation](#further-documentation)

## Requirements

- A Strava account and an [API application](https://www.strava.com/settings/api) (`STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`).
- Docker (optionally Docker Compose) to run the image.
- For OAuth: a correct **Authorization Callback Domain** in Strava and **`PUBLIC_BASE_URL`** matching the URL you use in the browser.

## Strava API app and OAuth

1. Create an application in [Strava API Settings](https://www.strava.com/settings/api).
2. **Authorization Callback Domain** — host only (no `http://`, no path), e.g. `192.168.1.50` or `localhost`. Details: [docs/strava-oauth.md](docs/strava-oauth.md).
3. The redirect URL this app always uses is:

   **`{PUBLIC_BASE_URL}/api/auth/callback`**

   Example: `http://192.168.1.50:8787/api/auth/callback`.

`PUBLIC_BASE_URL` must be the **same** URL you open in the browser (scheme, host, port).

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `STRAVA_CLIENT_ID` | yes | Application ID from Strava |
| `STRAVA_CLIENT_SECRET` | yes | Application secret from Strava |
| `PUBLIC_BASE_URL` | yes | Public base URL of this service (e.g. `http://192.168.1.10:8787`), no trailing `/` |
| `DATA_DIR` | no | Directory for token storage (default `/data` in the container) |
| `MAX_ACTIVITY_PAGES` | no | How many pages of 200 activities to fetch (default `50`, ~10k activities) |

Copy `.env.example` to `.env` and fill in values (Compose loads `.env` from the project directory).

## Run with Docker / Compose

```bash
cp .env.example .env
# Edit .env — STRAVA_*, PUBLIC_BASE_URL
docker compose up -d --build
```

The app listens on port **8787** (see `docker-compose.yml`).

**Volume:** mount a host directory on **`/data`** so `strava_tokens.json` survives container restarts (otherwise you must connect Strava again after each restart).

## Unraid

1. **Docker:** add a container from an image built from this repo, or build locally and reference the image.
2. **Port:** map e.g. host `8787` → container `8787`.
3. **Path (appdata):**
   - Container path: `/data`
   - Host path: e.g. `/mnt/user/appdata/strava-merge/`
4. **Environment:** `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, `PUBLIC_BASE_URL` (e.g. `http://YOUR_UNRAID_IP:8787` — same URL you use to open the UI).
5. In the Strava app settings, set **Authorization Callback Domain** as described in [docs/strava-oauth.md](docs/strava-oauth.md).

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export STRAVA_CLIENT_ID=... STRAVA_CLIENT_SECRET=... PUBLIC_BASE_URL=http://localhost:8787
uvicorn app.main:app --reload --host 0.0.0.0 --port 8787
```

Open `http://localhost:8787` (Strava callback domain: `localhost`).

## HTTP API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/config` | Whether the client is configured, `redirect_uri`, `public_base_url` |
| GET | `/api/auth/status` | Whether a token is stored |
| GET | `/api/auth/login` | Redirect to Strava (OAuth) |
| GET | `/api/auth/callback` | OAuth callback (`code` query param) |
| POST | `/api/auth/logout` | Remove token from the server |
| GET | `/api/activities?days=90` | List activities |
| GET | `/api/activity/{id}` | One activity from Strava (**`device_name`**, type, distance, …) |
| GET | `/api/suggestions?days=60` | Suggested pairs to merge |
| POST | `/api/merge` | JSON: `{ "activity_ids": [id1, id2], "name", "description", "primary_activity_id": optional }` — `primary_activity_id` sets TCX **Sport** (must be one of the two ids; e.g. pick the head-unit activity). |
| GET | `/api/uploads/{upload_id}` | Strava file-upload status (`status`, `error`, `activity_id` when processed) |

## Logs and upload status

Server logs go to **stderr** (visible in Docker / Unraid container logs).

```bash
docker logs -f strava-merge-1
# or: docker compose logs -f
```

Look for lines from `app.merge_service` / `app.strava_service` (merge point counts, TCX size, upload id, Strava `status`).

After a merge, the UI shows an **upload id**. Poll Strava until the activity exists:

```bash
curl -s "http://YOUR_HOST:8787/api/uploads/UPLOAD_ID"
```

(Uses the token stored on the server; same single-user setup as the web UI.)

Typical Strava `status` values: processing queue → finished with `activity_id`, or `error` with a message if the file was rejected.

## Merging back-to-back activities

If one workout **ends** and the **next starts later** (no overlap), the merge still **sorts all GPS points by time**. You get one activity whose track is: full first session, then full second session. **Distance** in the TCX is cumulative (second leg’s stream distances are offset by the first leg’s max distance).

**Map behavior:** there can be a **long straight line** (or jump) between the last point of session A and the first point of session B if you moved to a new start location — that is normal. **Overlapping** duplicate recordings (watch + head unit on the same ride) interleave by timestamp after sorting, which can look messy; this tool is best for **sequential** segments or **overlapping** twin uploads you understand.

**Primary activity / device:** Strava’s [detailed activity](https://developers.strava.com/docs/reference/#api-models-DetailedActivity) includes **`device_name`** (e.g. Garmin Edge vs watch). Use **`GET /api/activity/{id}`** in the UI to show it. **`primary_activity_id`** in `/api/merge` only changes the TCX **`Sport`** type (e.g. ensure **Ride** from the head unit); it does not remove or prefer one GPS stream over the other.

## Why the CLI kept asking for auth

The Strava authorization code (`?code=...`) is **single-use**. This app stores a `refresh_token` in `{DATA_DIR}/strava_tokens.json` and refreshes the access token automatically.

## Troubleshooting

- **`redirect_uri` mismatch** — see [docs/strava-oauth.md](docs/strava-oauth.md); align `PUBLIC_BASE_URL` and the Strava callback domain.
- **Session gone after restart** — no persistent volume on `/data` or wrong `DATA_DIR`.
- **Empty activity list** — increase the day range in the UI or check `MAX_ACTIVITY_PAGES`.
- **TCX upload errors** — check app scopes (`activity:write`) and Strava rate limits.
- **Upload accepted but no activity** — Strava processes uploads asynchronously; check [Logs](#logs-and-upload-status) and `GET /api/uploads/{id}`. If `error` is set, Strava rejected the file (see message).

## Further documentation

- [Strava OAuth: redirect URI and callback domain](docs/strava-oauth.md)

## License

Add a `LICENSE` file if you publish the repository publicly.
