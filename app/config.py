from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    strava_client_id: str = ""
    strava_client_secret: str = ""
    # Public URL of this app, e.g. http://192.168.1.10:8787 — used for OAuth redirect
    public_base_url: str = "http://localhost:8787"

    # Where tokens and temp files live (mount a Docker volume here)
    data_dir: Path = Path("/data")  # override with DATA_DIR=/path

    # Strava paginates 200 per page; 50 pages = max ~10k activities listed
    max_activity_pages: int = 50

    @property
    def redirect_uri(self) -> str:
        base = self.public_base_url.rstrip("/")
        return f"{base}/api/auth/callback"


settings = Settings()
