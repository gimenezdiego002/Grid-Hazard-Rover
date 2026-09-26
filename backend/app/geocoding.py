"""Google Geocoding boundary for source records that lack coordinates."""

from __future__ import annotations

from functools import lru_cache

import httpx

from backend.app.config import get_settings
from shared.schemas import Geometry, PointGeometry

GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"


class GeocodingError(RuntimeError):
    pass


@lru_cache(maxsize=256)
def geocode_address(address: str) -> PointGeometry:
    """Resolve one address; Google returns lat/lng but GeoJSON stores lng/lat."""
    cleaned = address.strip()
    if not cleaned:
        raise GeocodingError("An address is required when coordinates are missing.")
    api_key = get_settings().google_maps_api_key
    if not api_key:
        raise GeocodingError("GOOGLE_MAPS_API_KEY is not configured.")
    try:
        response = httpx.get(
            GEOCODING_URL,
            params={"address": cleaned, "key": api_key},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        raise GeocodingError("Google Geocoding request failed.") from None
    if payload.get("status") != "OK" or not payload.get("results"):
        raise GeocodingError(f"Google Geocoding returned {payload.get('status', 'no result')}.")
    location = payload["results"][0]["geometry"]["location"]
    try:
        return PointGeometry(coordinates=(float(location["lng"]), float(location["lat"])))
    except (KeyError, TypeError, ValueError):
        raise GeocodingError("Google Geocoding returned malformed coordinates.") from None


def location_or_geocode(
    location: Geometry | None, address: str | None
) -> Geometry:
    """Never geocode when a source already supplies canonical geometry."""
    if location is not None:
        return location
    if address is None:
        raise GeocodingError("A location or address is required.")
    return geocode_address(address)
