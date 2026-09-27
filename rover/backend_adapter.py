"""Prepare camera bytes and trusted context for Grid's existing photo API."""

from __future__ import annotations

from dataclasses import dataclass

from rover.location import LocationFix


@dataclass(frozen=True)
class PhotoObservation:
    jpeg: bytes
    location: LocationFix
    robot_id: str

    def __post_init__(self) -> None:
        if not self.jpeg.startswith(b"\xff\xd8") or not self.jpeg.endswith(b"\xff\xd9"):
            raise ValueError("camera frame must be a complete JPEG")

    def multipart(self) -> tuple[dict, dict]:
        longitude, latitude = self.location.location.coordinates
        files = {"image": ("fnk0052-capture.jpg", self.jpeg, "image/jpeg")}
        data = {
            "longitude": str(longitude),
            "latitude": str(latitude),
            "timestamp": self.location.captured_at.isoformat(),
            "source": f"{'simulated' if self.location.simulated else 'physical'}:{self.robot_id}:{self.location.source}",
        }
        return files, data
