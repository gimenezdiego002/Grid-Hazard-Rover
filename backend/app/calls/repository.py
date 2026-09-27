"""Idempotent memory/Mongo persistence for call reports and reviews."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Protocol

from pymongo import ASCENDING, DESCENDING
from pymongo.errors import PyMongoError

from backend.app.calls.models import CallReport, RecordingStatus, ReviewStatus
from backend.app.config import get_settings
from backend.app.database import get_database


class CallRepository(Protocol):
    def save(self, report: CallReport) -> CallReport: ...
    def list(self, *, limit: int, company_id: str | None = None) -> list[CallReport]: ...
    def get(self, conversation_id: str) -> CallReport | None: ...
    def review(self, conversation_id: str, status: ReviewStatus, note: str | None) -> CallReport | None: ...
    def attach_audio(self, conversation_id: str, path: Path, digest: str) -> None: ...


class MemoryCallRepository:
    def __init__(self) -> None:
        self._reports: dict[str, CallReport] = {}
        self._audio: dict[str, tuple[Path, str]] = {}

    def _with_audio(self, report: CallReport) -> CallReport:
        audio = self._audio.get(report.conversation_id)
        if not audio:
            return report
        return report.model_copy(
            update={"recording_status": RecordingStatus.LOCAL_SAVED, "audio_sha256": audio[1]}
        )

    def save(self, report: CallReport) -> CallReport:
        previous = self._reports.get(report.conversation_id)
        if previous:
            report = report.model_copy(
                update={
                    "review_status": previous.review_status,
                    "reviewer_note": previous.reviewer_note,
                }
            )
        report = self._with_audio(report)
        self._reports[report.conversation_id] = report
        return report

    def list(self, *, limit: int, company_id: str | None = None) -> list[CallReport]:
        values = self._reports.values()
        if company_id:
            values = (item for item in values if item.company_id == company_id)
        return sorted(values, key=lambda item: item.ended_at, reverse=True)[:limit]

    def get(self, conversation_id: str) -> CallReport | None:
        report = self._reports.get(conversation_id)
        return self._with_audio(report) if report else None

    def review(self, conversation_id: str, status: ReviewStatus, note: str | None) -> CallReport | None:
        report = self._reports.get(conversation_id)
        if report is None:
            return None
        updated = report.model_copy(update={"review_status": status, "reviewer_note": note})
        self._reports[conversation_id] = updated
        return updated

    def attach_audio(self, conversation_id: str, path: Path, digest: str) -> None:
        self._audio[conversation_id] = (path, digest)
        report = self._reports.get(conversation_id)
        if report:
            self._reports[conversation_id] = self._with_audio(report)


class MongoCallRepository:
    collection_name = "call_reports"

    def __init__(self) -> None:
        self._indexed = False

    @property
    def collection(self):
        collection = get_database()[self.collection_name]
        if not self._indexed:
            collection.create_index([("conversation_id", ASCENDING)], unique=True)
            collection.create_index([("company_id", ASCENDING), ("ended_at", DESCENDING)])
            self._indexed = True
        return collection

    def save(self, report: CallReport) -> CallReport:
        previous = self.collection.find_one(
            {"conversation_id": report.conversation_id},
            {"review_status": 1, "reviewer_note": 1, "recording_status": 1, "audio_sha256": 1},
        )
        updates = {}
        if previous:
            for field in ("review_status", "reviewer_note", "recording_status", "audio_sha256"):
                if previous.get(field) is not None:
                    updates[field] = previous[field]
        report = report.model_copy(update=updates)
        self.collection.replace_one(
            {"conversation_id": report.conversation_id},
            report.model_dump(mode="json"),
            upsert=True,
        )
        return report

    def list(self, *, limit: int, company_id: str | None = None) -> list[CallReport]:
        query = {"company_id": company_id} if company_id else {}
        rows = self.collection.find(query, {"_id": False}).sort("ended_at", DESCENDING).limit(limit)
        return [CallReport.model_validate(row) for row in rows]

    def get(self, conversation_id: str) -> CallReport | None:
        row = self.collection.find_one({"conversation_id": conversation_id}, {"_id": False})
        return CallReport.model_validate(row) if row else None

    def review(self, conversation_id: str, status: ReviewStatus, note: str | None) -> CallReport | None:
        result = self.collection.find_one_and_update(
            {"conversation_id": conversation_id},
            {"$set": {"review_status": status.value, "reviewer_note": note}},
            projection={"_id": False},
            return_document=True,
        )
        return CallReport.model_validate(result) if result else None

    def attach_audio(self, conversation_id: str, path: Path, digest: str) -> None:
        # The private local path is deliberately not stored in Mongo. It is
        # derived from the validated conversation id on authenticated reads.
        self.collection.update_one(
            {"conversation_id": conversation_id},
            {"$set": {
                "recording_status": RecordingStatus.LOCAL_SAVED.value,
                "audio_sha256": digest,
            }},
        )


@lru_cache(maxsize=1)
def get_call_repository() -> CallRepository:
    settings = get_settings()
    return MongoCallRepository() if settings.mongodb_uri_has_valid_scheme else MemoryCallRepository()


def clear_call_repository_cache() -> None:
    get_call_repository.cache_clear()

