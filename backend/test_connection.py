"""Opt-in live Mongo smoke test; skipped during ordinary test discovery."""

from __future__ import annotations

import os
import unittest

from backend.app.database import close_mongo_client, get_mongo_client


@unittest.skipUnless(
    os.getenv("RUN_LIVE_MONGO_TESTS") == "1" and os.getenv("MONGODB_URI"),
    "Set RUN_LIVE_MONGO_TESTS=1 and MONGODB_URI for a live Atlas smoke test",
)
class MongoConnectionSmokeTest(unittest.TestCase):
    def tearDown(self) -> None:
        close_mongo_client()

    def test_ping(self) -> None:
        self.assertEqual(get_mongo_client().admin.command("ping")["ok"], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
