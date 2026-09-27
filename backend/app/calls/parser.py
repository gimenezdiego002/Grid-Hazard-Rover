"""Allowlisted conversion from ElevenLabs post-call payloads into call reports."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.calls.models import (
    CallAnalysis,
    CallReport,
    CallUrgency,
    RecordingStatus,
    TranscriptTurn,
)


def _text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    clean = " ".join(value.split()).strip()
    return clean[:limit] or None


def _collected(analysis: dict[str, Any], key: str) -> Any:
    results = analysis.get("data_collection_results")
    if not isinstance(results, dict):
        return None
    item = results.get(key)
    if isinstance(item, dict):
        return item.get("value")
    return item


def _urgency(analysis: dict[str, Any], transcript: list[TranscriptTurn]) -> CallUrgency:
    explicit = _text(_collected(analysis, "urgency"), 50)
    if explicit:
        normalized = explicit.lower()
        if normalized in {item.value for item in CallUrgency}:
            return CallUrgency(normalized)
    words = " ".join(turn.message.lower() for turn in transcript if turn.role == "user")
    if any(term in words for term in ("immediate danger", "electrocution", "live wire", "call 911", "fire")):
        return CallUrgency.EMERGENCY
    if any(term in words for term in ("exposed cable", "flood", "blocked road", "gas leak", "injury")):
        return CallUrgency.HIGH
    if any(term in words for term in ("pothole", "debris", "damaged", "vegetation")):
        return CallUrgency.MEDIUM
    return CallUrgency.LOW


def parse_transcription_event(payload: dict[str, Any]) -> CallReport:
    if payload.get("type") != "post_call_transcription":
        raise ValueError("unsupported webhook event")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("webhook data is missing")

    turns: list[TranscriptTurn] = []
    raw_transcript = data.get("transcript")
    if isinstance(raw_transcript, list):
        for raw in raw_transcript[:1_000]:
            if not isinstance(raw, dict):
                continue
            role = raw.get("role") if raw.get("role") in {"agent", "user"} else "unknown"
            message = _text(raw.get("message"), 20_000)
            if not message:
                continue
            seconds = raw.get("time_in_call_secs")
            if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds < 0:
                seconds = None
            turns.append(TranscriptTurn(role=role, message=message, time_in_call_seconds=seconds))

    raw_analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else {}
    summary = _text(raw_analysis.get("transcript_summary"), 10_000) or _text(
        _collected(raw_analysis, "summary"), 10_000
    ) or "Call completed; summary was not provided by the configured agent analysis."
    category = _text(_collected(raw_analysis, "category"), 100) or "general_feedback"
    sentiment = _text(_collected(raw_analysis, "sentiment"), 100) or "unknown"
    location = _text(_collected(raw_analysis, "location"), 500)
    actions_value = _collected(raw_analysis, "action_items")
    if isinstance(actions_value, list):
        actions = [text for item in actions_value[:20] if (text := _text(item, 1_000))]
    elif text := _text(actions_value, 1_000):
        actions = [text]
    else:
        actions = []
    successful = raw_analysis.get("call_successful")
    if not isinstance(successful, bool):
        successful = None

    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    duration = metadata.get("call_duration_secs", metadata.get("duration_seconds"))
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration < 0:
        duration = None
    event_timestamp = payload.get("event_timestamp")
    if not isinstance(event_timestamp, (int, float)) or isinstance(event_timestamp, bool):
        event_timestamp = datetime.now(timezone.utc).timestamp()
    dynamic = data.get("conversation_initiation_client_data")
    dynamic = dynamic if isinstance(dynamic, dict) else {}
    variables = dynamic.get("dynamic_variables")
    variables = variables if isinstance(variables, dict) else {}
    consent = variables.get("consent_to_record")
    if isinstance(consent, str):
        consent = consent.strip().lower() in {"yes", "true", "1", "agreed"}
    if not isinstance(consent, bool):
        consent = None
    has_audio = data.get("has_audio") is True

    return CallReport(
        conversation_id=str(data.get("conversation_id", "")).strip(),
        agent_id=str(data.get("agent_id", "")).strip(),
        agent_name=_text(data.get("agent_name"), 200),
        company_id=_text(variables.get("company_id"), 200),
        company_name=_text(variables.get("company_name"), 200),
        ended_at=datetime.fromtimestamp(event_timestamp, tz=timezone.utc),
        duration_seconds=duration,
        transcript=turns,
        analysis=CallAnalysis(
            summary=summary,
            category=category,
            sentiment=sentiment,
            urgency=_urgency(raw_analysis, turns),
            call_successful=successful,
            location_text=location,
            action_items=actions,
        ),
        has_audio=has_audio,
        recording_status=(
            RecordingStatus.PROVIDER_RETAINED if has_audio else RecordingStatus.NOT_AVAILABLE
        ),
        consent_to_record=consent,
    )

