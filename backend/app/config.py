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
    )
