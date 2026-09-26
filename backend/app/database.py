"""Lazy MongoDB access boundary. No startup connection, collections, or indexes."""

from __future__ import annotations

from threading import Lock
from typing import Any

from pymongo import MongoClient
from pymongo.database import Database

from backend.app.config import get_settings


class DatabaseConfigurationError(RuntimeError):
    """Database access was requested without the required configuration."""


_client: MongoClient[dict[str, Any]] | None = None
_client_lock = Lock()


def get_mongo_client() -> MongoClient[dict[str, Any]]:
    global _client
    settings = get_settings()
    if settings.mongodb_uri is None:
        raise DatabaseConfigurationError(
            "MONGODB_URI is not configured. Set it before requesting database access."
        )
    with _client_lock:
        if _client is None:
            _client = MongoClient(
                settings.mongodb_uri, connect=False, serverSelectionTimeoutMS=5000
            )
        return _client


def get_database() -> Database[dict[str, Any]]:
    return get_mongo_client()[get_settings().mongodb_db]


def close_mongo_client() -> None:
    global _client
    with _client_lock:
        if _client is not None:
            _client.close()
            _client = None
