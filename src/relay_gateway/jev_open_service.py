"""Opt-in loopback OpenJev worker. No hosted calls, robot commands or downloads."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import threading
import time
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware


class LocalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    state: str = Field(min_length=2, max_length=8192)
    choices: list[Literal["hold", "request_evidence", "escalate_gemini", "continue_monitoring"]] = Field(min_length=1, max_length=4)
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,160}$")
    timeout_seconds: float = Field(default=5.0, gt=0, le=10)

    @model_validator(mode="after")
    def bounded_payload(self):
        if len(self.state.encode("utf-8")) > 8192:
            raise ValueError("Controller state exceeds the UTF-8 byte limit")
        if len(set(self.choices)) != len(self.choices):
            raise ValueError("Supervisory choices must be distinct")
        return self


def create_app(provider, *, max_requests=100, metadata=None, telemetry=None):
    if type(max_requests) is not int or not 1 <= max_requests <= 100:
        raise ValueError("Local worker allowance must be 1..100 calls")
    app = FastAPI(title="Relay local OpenJev", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    lock = threading.Lock()
    state = {"requests": 0}

    @app.get("/health")
    def health():
        return {"service": "relay-local-openjev", "ready": True, "backend": "local_openjev",
                "inference_simulated": bool(getattr(provider, "simulated", True)),
                "model": getattr(provider, "model", "unknown"), "pid": os.getpid(),
                "hosted_api_requests": 0, "actuation_enabled": False,
                "busy": lock.locked(), "requests": state["requests"], "max_requests": max_requests,
                "metadata": metadata or {}, "resources": telemetry() if telemetry else {}}

    def infer(packet):
        if not lock.acquire(blocking=False):
            raise HTTPException(429, "Local worker busy; no automatic retry")
        try:
            if state["requests"] >= max_requests:
                raise HTTPException(429, "Local worker allowance exhausted")
            state["requests"] += 1
            response = provider.decide(packet.state, tuple(packet.choices), packet.operation_id,
                                       timeout_seconds=packet.timeout_seconds)
            return response.as_dict() if hasattr(response, "as_dict") else response
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "Local inference unavailable; retain safe hold") from None
        finally:
            lock.release()

    @app.post("/decide")
    async def decide(request: Request):
        if request.headers.get("origin"):
            raise HTTPException(403, "Browser-origin inference is disabled")
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise HTTPException(415, "Use JSON")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 20000:
                raise HTTPException(413, "Local request too large")
        try:
            packet = LocalDecisionRequest.model_validate_json(body)
        except (ValidationError, ValueError):
            raise HTTPException(422, "Invalid bounded local decision request") from None
        return await run_in_threadpool(infer, packet)

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description="Load a pinned cached OpenJev model on this laptop")
    parser.add_argument("--load-local", action="store_true", required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path(".state/openjev-cache"))
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--max-requests", type=int, default=100)
    parser.add_argument("--max-length", type=int, default=1024)
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("Use an unprivileged loopback port")
    if not 1 <= args.max_requests <= 100:
        parser.error("Local worker allowance must be 1..100 calls")
    if not 128 <= args.max_length <= 4096:
        parser.error("Local context length must be 128..4096 tokens")
    # Only this dedicated process is configured; the user's global environment
    # and other tasks are untouched. Inner model loading also stays offline.
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "HF_HUB_DISABLE_IMPLICIT_TOKEN"):
        os.environ[key] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    from .jev_open_provider import LocalOpenJevProvider
    import torch
    import uvicorn

    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise SystemExit("A compatible CUDA GPU with BF16 support is required by this local profile")
    # Claim the port before allocating another copy of the GPU model.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    listener.bind(("127.0.0.1", args.port))
    started = time.monotonic()
    try:
        torch.set_num_threads(8)
        provider = LocalOpenJevProvider.from_local_cache(allow_local=True, cache_dir=args.cache_dir,
                                                        device="cuda", max_length=args.max_length,
                                                        max_calls=args.max_requests)
        torch.cuda.synchronize()
        metadata = {"device": torch.cuda.get_device_name(0), "torch": torch.__version__,
                    "cuda_runtime": torch.version.cuda, "max_length": args.max_length,
                    "load_seconds": round(time.monotonic() - started, 3),
                    "model_allocated_bytes": torch.cuda.memory_allocated(),
                    "cloud_api_usd": "0", "energy_measured": False}
        def gpu_memory():
            return {"allocated_bytes": torch.cuda.memory_allocated(),
                    "reserved_bytes": torch.cuda.memory_reserved(),
                    "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
                    "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
                    "basis": "pytorch_worker_allocator_since_startup"}

        app = create_app(provider, max_requests=args.max_requests, metadata=metadata, telemetry=gpu_memory)
        print(json.dumps({"status": "loaded", "url": f"http://127.0.0.1:{args.port}", **metadata}), flush=True)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, workers=1,
                                             log_level="warning", access_log=False))
        server.run(sockets=[listener])
    finally:
        listener.close()


if __name__ == "__main__":
    main()
