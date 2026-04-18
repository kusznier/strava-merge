# Strava OAuth — redirect URI and callback domain

This app uses Strava’s standard OAuth 2.0 flow. After you authorize, Strava redirects the browser to the **callback** URL with `code=...`.

## Full redirect URL (this application)

```
{PUBLIC_BASE_URL}/api/auth/callback
```

Examples:

| How you open the UI in the browser | Set `PUBLIC_BASE_URL` to | Full redirect URI |
|-----------------------------------|---------------------------|-------------------|
| `http://192.168.1.50:8787` | `http://192.168.1.50:8787` | `http://192.168.1.50:8787/api/auth/callback` |
| `http://localhost:8787` | `http://localhost:8787` | `http://localhost:8787/api/auth/callback` |
| `https://merge.example.com` (reverse proxy) | `https://merge.example.com` | `https://merge.example.com/api/auth/callback` |

**Rule:** `PUBLIC_BASE_URL` must match the address bar exactly (same `http`/`https`, host, and non-default port if any). Otherwise Strava returns a `redirect_uri` mismatch error.

## Strava dashboard — “Authorization Callback Domain”

In [API settings](https://www.strava.com/settings/api) for your app, you enter **only the domain / host** (no `http://`, no path):

- For `http://192.168.1.50:8787` → **Callback domain:** `192.168.1.50`
- For `http://localhost:8787` → **Callback domain:** `localhost`
- For `https://merge.example.com` → **Callback domain:** `merge.example.com`

Strava validates the host in the `redirect_uri` parameter against what is allowed for the application.

### Port and LAN

If you use an IP and port (e.g. Unraid on a home network), the **callback domain** is usually the IP alone (`192.168.1.50`). The port is part of the full `redirect_uri` in the OAuth request and must match what the app sends (`PUBLIC_BASE_URL`).

## Client ID and Client Secret

- **Client ID** and **Client Secret** come from the same Strava API application page.
- In Docker, set `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET` (see `.env.example`).

## Common issues

| Symptom | Cause | What to do |
|---------|-------|------------|
| `redirect_uri` mismatch | Wrong domain in Strava or `PUBLIC_BASE_URL` differs from the browser URL | Align host/port/scheme; fix the callback domain in Strava |
| Authorization code “doesn’t work” the second time | OAuth codes are **single-use** | Don’t reuse an old code — click Connect again; tokens are stored in `/data` |
| 401 after a while | Access token expired | The app should refresh via refresh token; if 401 persists, log out and connect again |

## Related files in this repo

- Token exchange: `app/strava_service.py` (`exchange_code`, `refresh_access_token`)
- Token storage: `app/tokens.py` → `{DATA_DIR}/strava_tokens.json`
- Public URL: `app/config.py` → `PUBLIC_BASE_URL`, `redirect_uri`
