"""Environment configuration; process variables take precedence over root .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
LOCAL_FRONTEND = "http://localhost:5173"


@dataclass(frozen=True)
class Settings:
    mongodb_uri: str | None = field(default=None, repr=False)
    mongodb_db: str = "grid_hazard_rover"
    frontend_url: str = LOCAL_FRONTEND
    # Optional at startup; validate before a future classification request.
    gemini_api_key: str | None = field(default=None, repr=False)
    gemini_model: str | None = None
    google_maps_api_key: str | None = field(default=None, repr=False)
    elevenlabs_api_key: str | None = field(default=None, repr=False)
    elevenlabs_voice_id: str | None = None
    elevenlabs_agent_id: str | None = None
    elevenlabs_webhook_secret: str | None = field(default=None, repr=False)
    calls_dashboard_token: str | None = field(default=None, repr=False)
    elevenlabs_save_call_audio: bool = False
    call_audio_storage_dir: Path = Path(".state/call-audio")
    call_audio_max_bytes: int = 15_000_000
    discord_webhook_url: str | None = field(default=None, repr=False)

    @property
    def mongodb_uri_has_valid_scheme(self) -> bool:
        return bool(
            self.mongodb_uri
            and self.mongodb_uri.startswith(("mongodb://", "mongodb+srv://"))
        )

    @property
    def cors_origins(self) -> list[str]:
        return list(dict.fromkeys([LOCAL_FRONTEND, self.frontend_url]))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(ROOT_ENV_FILE, override=False)
    origin = (os.getenv("FRONTEND_URL", "").strip() or LOCAL_FRONTEND).rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("FRONTEND_URL must be an HTTP(S) origin without a path")
    return Settings(
        mongodb_uri=os.getenv("MONGODB_URI", "").strip() or None,
        mongodb_db=os.getenv("MONGODB_DB", "").strip() or "grid_hazard_rover",
        frontend_url=origin,
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip() or None,
        gemini_model=os.getenv("GEMINI_MODEL", "").strip() or None,
        google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY", "").strip() or None,
        elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", "").strip() or None,
        elevenlabs_voice_id=os.getenv("ELEVENLABS_VOICE_ID", "").strip() or None,
        elevenlabs_agent_id=os.getenv("ELEVENLABS_AGENT_ID", "").strip() or None,
        elevenlabs_webhook_secret=os.getenv("ELEVENLABS_WEBHOOK_SECRET", "").strip() or None,
        calls_dashboard_token=os.getenv("CALLS_DASHBOARD_TOKEN", "").strip() or None,
        elevenlabs_save_call_audio=os.getenv("ELEVENLABS_SAVE_CALL_AUDIO", "false").strip().lower()
        in {"1", "true", "yes", "on"},
        call_audio_storage_dir=Path(
            os.getenv("CALL_AUDIO_STORAGE_DIR", ".state/call-audio").strip()
            or ".state/call-audio"
        ),
        call_audio_max_bytes=int(
            os.getenv("CALL_AUDIO_MAX_BYTES", "15000000").strip() or "15000000"
        ),
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL", "").strip() or None,
    )
