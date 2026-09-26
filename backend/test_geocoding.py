"""Google geocoding is fully mocked; tests make no network requests."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.app import geocoding
from backend.app.config import Settings
from shared.schemas import PointGeometry


class GeocodingTests(unittest.TestCase):
    def setUp(self) -> None:
        geocoding.geocode_address.cache_clear()
        self.addCleanup(geocoding.geocode_address.cache_clear)

    def test_existing_coordinates_bypass_google(self) -> None:
        point = PointGeometry(coordinates=(-80.36, 25.76))
        with patch("backend.app.geocoding.httpx.get") as request:
            self.assertIs(geocoding.location_or_geocode(point, "ignored"), point)
        request.assert_not_called()

    def test_google_lat_lng_is_converted_to_geojson_order_and_cached(self) -> None:
        response = MagicMock()
        response.json.return_value = {
            "status": "OK",
            "results": [{"geometry": {"location": {"lat": 25.76, "lng": -80.36}}}],
        }
        with patch("backend.app.geocoding.get_settings", return_value=Settings(
            google_maps_api_key="unit-test-key"
        )), patch("backend.app.geocoding.httpx.get", return_value=response) as request:
            first = geocoding.geocode_address("Miami demo address")
            second = geocoding.geocode_address("Miami demo address")
        self.assertEqual(first.coordinates, (-80.36, 25.76))
        self.assertIs(first, second)
        request.assert_called_once()

    def test_missing_key_and_zero_results_are_clear(self) -> None:
        with patch("backend.app.geocoding.get_settings", return_value=Settings()):
            with self.assertRaisesRegex(geocoding.GeocodingError, "GOOGLE_MAPS_API_KEY"):
                geocoding.geocode_address("Miami")
        geocoding.geocode_address.cache_clear()
        response = MagicMock()
        response.json.return_value = {"status": "ZERO_RESULTS", "results": []}
        with patch("backend.app.geocoding.get_settings", return_value=Settings(
            google_maps_api_key="test"
        )), patch("backend.app.geocoding.httpx.get", return_value=response):
            with self.assertRaisesRegex(geocoding.GeocodingError, "ZERO_RESULTS"):
                geocoding.geocode_address("not found")


if __name__ == "__main__":
    unittest.main(verbosity=2)
