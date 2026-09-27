"""ElevenLabs webhooks and authenticated company call-review endpoints."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import ValidationError
from pymongo.errors import PyMongoError

from backend.app.calls.models import CallReport, CallReportSummary, ReviewUpdate
from backend.app.calls.parser import parse_transcription_event
from backend.app.calls.repository import CallRepository, get_call_repository
from backend.app.calls.security import (
    InvalidWebhookSignature,
    token_matches,
    verify_elevenlabs_signature,
)
from backend.app.config import get_settings


router = APIRouter(tags=["AI call intake"])
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
MAX_TRANSCRIPTION_BYTES = 2_000_000


def company_access(authorization: Annotated[str | None, Header()] = None) -> None:
    if not token_matches(authorization, get_settings().calls_dashboard_token):
        raise HTTPException(status_code=401, detail="Company call access requires a valid bearer token")


CompanyAccess = Annotated[None, Depends(company_access)]


async def _verified_payload(request: Request, max_bytes: int) -> dict:
    settings = get_settings()
    if not settings.elevenlabs_webhook_secret:
        raise HTTPException(status_code=503, detail="ElevenLabs webhook is not configured")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(status_code=413, detail="Webhook payload is too large")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from None
    body = await request.body()
    if len(body) > max_bytes:
        raise HTTPException(status_code=413, detail="Webhook payload is too large")
    try:
        verify_elevenlabs_signature(
            body,
            request.headers.get("elevenlabs-signature"),
            settings.elevenlabs_webhook_secret,
        )
    except InvalidWebhookSignature:
        raise HTTPException(status_code=401, detail="Invalid webhook signature") from None
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Webhook body must be valid JSON") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook body must be a JSON object")
    return payload


@router.post("/webhooks/elevenlabs/post-call")
async def post_call(request: Request) -> dict[str, str]:
    payload = await _verified_payload(request, MAX_TRANSCRIPTION_BYTES)
    if payload.get("type") != "post_call_transcription":
        raise HTTPException(status_code=400, detail="Unsupported ElevenLabs event type")
    try:
        report = parse_transcription_event(payload)
        get_call_repository().save(report)
    except (ValueError, ValidationError):
        raise HTTPException(status_code=422, detail="Post-call payload does not match the expected contract") from None
    except PyMongoError:
        raise HTTPException(status_code=503, detail="Call storage unavailable") from None
    return {"status": "accepted", "conversation_id": report.conversation_id}


@router.post("/webhooks/elevenlabs/post-call-audio")
async def post_call_audio(request: Request) -> dict[str, str]:
    settings = get_settings()
    payload = await _verified_payload(request, settings.call_audio_max_bytes * 2)
    if payload.get("type") != "post_call_audio":
        raise HTTPException(status_code=400, detail="Unsupported ElevenLabs event type")
    if not settings.elevenlabs_save_call_audio:
        return {"status": "ignored", "reason": "local audio saving is disabled"}
    data = payload.get("data")
    if not isinstance(data, dict) or not SAFE_ID.fullmatch(str(data.get("conversation_id", ""))):
        raise HTTPException(status_code=422, detail="Invalid conversation id")
    conversation_id = str(data["conversation_id"])
    try:
        audio = base64.b64decode(data.get("full_audio", ""), validate=True)
    except (binascii.Error, ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Invalid audio payload") from None
    if not audio or len(audio) > settings.call_audio_max_bytes:
        raise HTTPException(status_code=413, detail="Call audio is empty or too large")
    if not (audio.startswith(b"ID3") or audio[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}):
        raise HTTPException(status_code=422, detail="Call audio is not a recognized MP3")
    root = settings.call_audio_storage_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = (root / f"{conversation_id}.mp3").resolve()
    if path.parent != root:
        raise HTTPException(status_code=422, detail="Invalid conversation id")
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(audio)
    temporary.replace(path)
    digest = hashlib.sha256(audio).hexdigest()
    try:
        get_call_repository().attach_audio(conversation_id, path, digest)
    except PyMongoError:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=503, detail="Call storage unavailable") from None
    return {"status": "saved", "conversation_id": conversation_id, "sha256": digest}


@router.get("/api/calls", response_model=list[CallReportSummary])
def list_calls(
    _: CompanyAccess,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    company_id: Annotated[str | None, Query(max_length=200)] = None,
) -> list[CallReportSummary]:
    try:
        reports = get_call_repository().list(limit=limit, company_id=company_id)
    except (PyMongoError, ValidationError):
        raise HTTPException(status_code=503, detail="Call storage unavailable") from None
    return [CallReportSummary.model_validate(item.model_dump(exclude={"transcript", "agent_id", "agent_name", "has_audio", "audio_sha256", "reviewer_note", "source"})) for item in reports]


@router.get("/api/calls/{conversation_id}", response_model=CallReport)
def call_detail(conversation_id: str, _: CompanyAccess) -> CallReport:
    if not SAFE_ID.fullmatch(conversation_id):
        raise HTTPException(status_code=422, detail="Invalid conversation id")
    try:
        report = get_call_repository().get(conversation_id)
    except (PyMongoError, ValidationError):
        raise HTTPException(status_code=503, detail="Call storage unavailable") from None
    if report is None:
        raise HTTPException(status_code=404, detail="Call not found")
    return report


@router.patch("/api/calls/{conversation_id}/review", response_model=CallReport)
def update_review(conversation_id: str, update: ReviewUpdate, _: CompanyAccess) -> CallReport:
    if not SAFE_ID.fullmatch(conversation_id):
        raise HTTPException(status_code=422, detail="Invalid conversation id")
    try:
        report = get_call_repository().review(conversation_id, update.status, update.note)
    except (PyMongoError, ValidationError):
        raise HTTPException(status_code=503, detail="Call storage unavailable") from None
    if report is None:
        raise HTTPException(status_code=404, detail="Call not found")
    return report


@router.get("/api/calls/{conversation_id}/audio")
def call_audio(conversation_id: str, _: CompanyAccess):
    if not SAFE_ID.fullmatch(conversation_id):
        raise HTTPException(status_code=422, detail="Invalid conversation id")
    settings = get_settings()
    path = (settings.call_audio_storage_dir.resolve() / f"{conversation_id}.mp3").resolve()
    if path.parent != settings.call_audio_storage_dir.resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail="Local call audio is not available")
    return FileResponse(path, media_type="audio/mpeg", filename=f"{conversation_id}.mp3")

