"""Application configuration.

Every tunable knob lives here and is sourced from environment variables (or an
optional ``backend/.env`` file). Nothing else in the codebase reads
``os.environ`` directly, which keeps configuration in one auditable place and
makes the test suite able to reconfigure the app by setting env vars before the
application is imported.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/  (…/backend/app/config.py -> …/backend)
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime settings, validated by pydantic on startup."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- general ----------------------------------------------------------
    app_name: str = "Meeting Planner API"
    api_prefix: str = "/api"
    environment: str = "development"

    # --- persistence ------------------------------------------------------
    # Default: a file-backed SQLite database next to the backend package.
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'meeting_planner.db').as_posix()}"

    # --- authentication ---------------------------------------------------
    # The default secret is intentionally obvious: production deployments MUST
    # override it via the JWT_SECRET_KEY environment variable.
    jwt_secret_key: str = "insecure-dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 12 * 60  # 12 hours

    # --- uploads ----------------------------------------------------------
    upload_dir: Path = BACKEND_DIR / "uploads"
    avatar_max_bytes: int = 2 * 1024 * 1024  # 2 MiB
    avatar_edge_px: int = 256  # avatars are normalised to a 256x256 square

    # --- CORS -------------------------------------------------------------
    # Set as a JSON list when overriding, e.g. CORS_ORIGINS='["https://app.example"]'
    cors_origins: list[str] = [
        "http://localhost:4200",
        "http://127.0.0.1:4200",
    ]

    # --- domain rules -----------------------------------------------------
    meeting_min_duration_minutes: int = 5
    meeting_max_duration_minutes: int = 7 * 24 * 60  # a week
    meeting_max_participants: int = 50

    @property
    def avatar_dir(self) -> Path:
        """Directory holding processed avatar images."""
        return self.upload_dir / "avatars"

    @property
    def static_url_prefix(self) -> str:
        """URL prefix under which ``upload_dir`` is served."""
        return "/static"


@lru_cache
def get_settings() -> Settings:
    """Cached accessor so the ``.env`` file is parsed exactly once."""
    return Settings()


settings = get_settings()
