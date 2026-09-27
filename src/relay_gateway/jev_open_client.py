"""Explicit loopback client for the standalone local OpenJev worker."""

from __future__ import annotations

import json
import math
import time
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from pollard_jev.providers.openjev import CHECKPOINT, REPOSITORY, REVISION

from .jev_provider import JevDecision


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LoopbackOpenJevProvider:
    """No hosted API, ambient proxy, retries, redirects or automatic startup."""

    simulated = False
    mode = "local"
    model = f"{REPOSITORY}/{CHECKPOINT}"

    def __init__(self, *, allow_local=False, port=8770):
        if allow_local is not True:
            raise ValueError("Connecting to local inference requires allow_local=True")
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError("Use an unprivileged loopback port")
        self._base = f"http://127.0.0.1:{port}"
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())
        self.calls = 0

    def _request(self, path, payload=None, timeout=2):
        body = None if payload is None else json.dumps(payload, allow_nan=False).encode()
        request = Request(self._base + path, data=body, headers={"Content-Type": "application/json"})
        with self._opener.open(request, timeout=timeout) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("Local response exceeds limit")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Invalid local response")
        return result

    def health(self):
        result = self._request("/health")
        if (result.get("service") != "relay-local-openjev" or result.get("ready") is not True
                or result.get("inference_simulated") is not False or result.get("model") != self.model
                or result.get("actuation_enabled") is not False or result.get("hosted_api_requests") != 0):
            raise ValueError("Local worker identity is not the expected actual OpenJev service")
        return result

    def decide(self, state, choices, operation_id, timeout_seconds=5.0):
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= 10):
            raise ValueError("Local deadline must be positive and at most 10 seconds")
        started = time.monotonic()
        self.calls += 1
        try:
            response = self._request("/decide", {"state": state, "choices": list(choices),
                "operation_id": operation_id, "timeout_seconds": timeout_seconds}, timeout_seconds)
            decision = JevDecision(**response)
            metrics = decision.metrics
            if (decision.operation_id != operation_id or decision.model != self.model
                    or decision.simulated is not False or decision.confidence is not None
                    or decision.status not in {"completed", "blocked", "failed"}
                    or metrics.get("revision") != REVISION or metrics.get("api_requests") != 0
                    or metrics.get("local_inference") is not True
                    or (decision.status == "completed" and decision.choice not in choices)
                    or (decision.status != "completed" and decision.choice is not None)):
                raise ValueError("Invalid local decision provenance")
            if time.monotonic() - started >= timeout_seconds:
                raise TimeoutError("Local response arrived after deadline")
            return decision
        except Exception:
            # A timed-out worker may still be computing. The controller latches
            # hold and the single-flight worker rejects overlapping requests.
            return JevDecision(None, "unknown", "local_worker_unavailable_or_late", None,
                self.model, operation_id, False, {"calls": 1, "dispatches": None,
                "api_requests": 0, "estimated_usd": "0", "actual_paid_api_usd": "0",
                "latency_ms": round((time.monotonic() - started) * 1000, 3),
                "revision": REVISION, "local_inference": True,
                "input_tokens": None, "output_tokens": None, "energy_joules": None})
