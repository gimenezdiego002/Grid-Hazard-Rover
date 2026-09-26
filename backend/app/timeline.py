"""Deterministic comparison of incomplete construction date ranges."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

COORDINATION_WINDOW_DAYS = 180


class TimelineRelationship(str, Enum):
    OVERLAP = "overlap"
    WITHIN_WINDOW = "within_180_days"
    OUTSIDE_WINDOW = "outside_180_days"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TimelineResult:
    relationship: TimelineRelationship
    overlap: bool | None
    gap_days: int | None

    @property
    def coordinates(self) -> bool:
        return self.relationship in {
            TimelineRelationship.OVERLAP,
            TimelineRelationship.WITHIN_WINDOW,
        }


def _known_range(start: date | None, end: date | None) -> tuple[date, date] | None:
    if start is None and end is None:
        return None
    known_start = start or end
    known_end = end or start
    assert known_start is not None and known_end is not None
    if known_end < known_start:
        raise ValueError("end date must not precede start date")
    return known_start, known_end


def compare_timelines(
    left_start: date | None,
    left_end: date | None,
    right_start: date | None,
    right_end: date | None,
) -> TimelineResult:
    left = _known_range(left_start, left_end)
    right = _known_range(right_start, right_end)
    if left is None or right is None:
        return TimelineResult(TimelineRelationship.UNKNOWN, None, None)
    if left[0] <= right[1] and right[0] <= left[1]:
        return TimelineResult(TimelineRelationship.OVERLAP, True, 0)
    if left[1] < right[0]:
        gap = (right[0] - left[1]).days
    else:
        gap = (left[0] - right[1]).days
    relationship = (
        TimelineRelationship.WITHIN_WINDOW
        if gap <= COORDINATION_WINDOW_DAYS
        else TimelineRelationship.OUTSIDE_WINDOW
    )
    return TimelineResult(relationship, False, gap)
