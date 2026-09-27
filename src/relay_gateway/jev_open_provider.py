"""Explicit, cached local OpenJev NLI supervision; no hosted API or actuator.

The independent AlexWortega/OpenJev checkpoint is not TypeSafe Jev. Importing
this module and constructing test doubles never loads weights. Real loading
requires ``from_local_cache(allow_local=True)`` and a previously cached pinned
snapshot; downloading remains a separate operator-controlled task.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from typing import Callable

from pollard_jev.contracts import ActionChoice, DecisionRequest, Observation, ProviderResult
from pollard_jev.providers.openjev import CHECKPOINT, REPOSITORY, REVISION, OpenJevProvider

from .jev_provider import JevDecision, MAX_STATE_BYTES


ACTION_HYPOTHESES = {
    "hold": "The simulated inspection lacks a supported next step and should remain on hold for review.",
    "request_evidence": "The controller reports missing, stale, or unsupported observations, so another structured observation is needed while holding.",
    "escalate_gemini": "The controller reports an alarm or conflicting observations, so Gemini interpretation is needed while holding.",
    "continue_monitoring": "The controller reports fresh observations, no alarm, and permission for passive monitoring without motion.",
}
_HEALTH = ("fresh", "missing", "stale", "unsupported", "conflicting")
_HELPER_SHA256 = "071670d0879963ee69600ed31f0f3d5a37bee314461709477e8ac0e25f33fd97"
_CONFIG_SHA256 = "477bed7614828c875db38b952835af9ca2fb5fa024af56cda8a708181db76a07"


def _verify_pinned_cache(cache_dir):
    """Inspect the cached helper before the package is allowed to execute it."""
    from huggingface_hub import snapshot_download

    snapshot = Path(snapshot_download(
        repo_id=REPOSITORY, revision=REVISION, cache_dir=cache_dir,
        local_files_only=True, token=False,
        allow_patterns=["modeling_openjev.py", f"{CHECKPOINT}/*"],
    ))
    helper = snapshot / "modeling_openjev.py"
    if hashlib.sha256(helper.read_bytes()).hexdigest() != _HELPER_SHA256:
        raise ValueError("Cached OpenJev helper differs from the reviewed pinned source")
    # The package also enforces NLI labels. Inspect that config before entering
    # its executable loader; the installer separately hashes the 9 GB weights.
    config_bytes = (snapshot / CHECKPOINT / "config.json").read_bytes()
    if hashlib.sha256(config_bytes).hexdigest() != _CONFIG_SHA256:
        raise ValueError("Cached OpenJev config differs from the reviewed pinned source")
    config = json.loads(config_bytes)
    if not isinstance(config, dict) or config.get("id2label") != {"0": "contradiction", "1": "entailment", "2": "neutral"}:
        raise ValueError("Cached OpenJev config has unreviewed NLI labels")
    return snapshot


def _bounded_probability(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be a finite number in [0, 1]")
    return float(value)


class _ContextOverflow(ValueError):
    pass


class _LocalDeadline(ValueError):
    pass


class _ContextCheckedEncoder:
    """Inspect complete NLI pairs before the pinned helper can truncate them.

    Measurements are tokenizer lengths of unpadded complete premise/hypothesis
    pairs. They are not hosted billing tokens or measurements of GPU work.
    """

    def __init__(self, encoder, *, required: bool):
        self.encoder, self.required = encoder, required
        self.measurement = {}
        self.forward_calls = 0
        self.before_compute = None

    def predict_hypotheses(self, premise, hypotheses):
        self.measurement = {}
        tokenizer = getattr(self.encoder, "tok", None)
        maximum = getattr(self.encoder, "max_len", None)
        template = getattr(self.encoder, "template", None)
        if callable(tokenizer) and type(maximum) is int and maximum > 0 and isinstance(template, str):
            lengths = []
            for hypothesis in hypotheses:
                text = template.format(premise=premise.strip(), hypothesis=hypothesis.strip())
                tokens = tokenizer(text, truncation=False, padding=False)["input_ids"]
                if not isinstance(tokens, list) or any(type(token) is not int for token in tokens):
                    raise ValueError("Encoder tokenizer did not expose token IDs")
                lengths.append(len(tokens))
            self.measurement = {
                "tokenized_pair_lengths": lengths, "unshared_input_tokens": sum(lengths),
                "maximum_context_tokens": maximum,
                "tokenization_basis": "cached_encoder_tokenizer_complete_unpadded_pairs",
                "token_measurement": "tokenized_pairs_available_billing_and_compute_tokens_unmeasured",
                "input_context_truncated": False,
            }
            if any(length > maximum for length in lengths):
                raise _ContextOverflow("NLI pair exceeds model context")
        elif self.required:
            raise ValueError("Loaded encoder lacks reviewed tokenization fields")
        if self.before_compute:
            self.before_compute()
        self.forward_calls += 1
        return self.encoder.predict_hypotheses(premise, hypotheses)


class LocalOpenJevProvider:
    """Relay-shaped adapter over the real package's independent NLI interface.

    The selection threshold/margin are uncalibrated demonstration settings,
    never physical-success probabilities. No action runs here. Calls are
    synchronous: a deadline rejects the result after return but cannot stop
    CUDA/native compute. One instance permits only one in-flight inference.
    """

    def __init__(self, *, provider: OpenJevProvider, acceptance_threshold=0.8,
                 minimum_margin=0.15, max_calls: int = 20,
                 clock: Callable[[], float] = time.monotonic):
        # Direct construction is reserved for the package's synthetic encoder
        # pathway. Real model loading must pass through the explicit factory.
        if not isinstance(provider, OpenJevProvider) or provider.identity.synthetic is not True:
            raise ValueError("Use explicit from_local_cache for a real local model")
        self._initialize(provider, acceptance_threshold, minimum_margin, max_calls, clock)

    def _initialize(self, provider, threshold, margin, max_calls, clock):
        self.acceptance_threshold = _bounded_probability(threshold, "acceptance_threshold")
        self.minimum_margin = _bounded_probability(margin, "minimum_margin")
        if type(max_calls) is not int or not 0 <= max_calls <= 100:
            raise ValueError("max_calls must be an integer in [0, 100]")
        self._encoder_guard = _ContextCheckedEncoder(provider._encoder, required=not provider.identity.synthetic)
        # Preserve the actual package mapping and identity while wrapping only
        # the inspected encoder interface, before its truncating implementation.
        self._provider = OpenJevProvider(self._encoder_guard, model=provider.identity.model,
                                        model_version=provider.identity.model_version,
                                        synthetic=provider.identity.synthetic)
        self.identity = provider.identity
        self.model = provider.identity.model
        self.simulated = provider.identity.synthetic
        self.mode = "fixture" if self.simulated else "local"
        self.max_calls, self._clock = max_calls, clock
        self.calls = 0
        self.load_latency_ms = None
        self._seen: set[str] = set()
        self._lock = threading.Lock()
        self._closed = False

    @classmethod
    def from_local_cache(cls, *, allow_local: bool = False, cache_dir: str | Path | None = None,
                         device: str = "cuda", max_length: int = 2048,
                         acceptance_threshold=0.8, minimum_margin=0.15,
                         max_calls: int = 20) -> LocalOpenJevProvider:
        """Explicit cached-only load using the package's fixed repo/revision.

        The upstream factory sets local_files_only=True and checks the pinned
        helper, weight, tokenizer and label config before executing the helper.
        Missing weights fail; this method never downloads or selects a revision.
        """
        if allow_local is not True:
            raise ValueError("Local model loading requires allow_local=True")
        if device not in {"cuda", "cpu"}:
            raise ValueError("Select an explicit cuda or cpu device")
        if type(max_length) is not int or not 128 <= max_length <= 4096:
            raise ValueError("max_length must be an integer in [128, 4096]")
        _bounded_probability(acceptance_threshold, "acceptance_threshold")
        _bounded_probability(minimum_margin, "minimum_margin")
        if type(max_calls) is not int or not 0 <= max_calls <= 100:
            raise ValueError("max_calls must be an integer in [0, 100]")
        # Set before optional model-library imports. These process settings are
        # intentional for this explicit offline local-inference worker.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        started = time.monotonic()
        _verify_pinned_cache(cache_dir)
        provider = OpenJevProvider.from_local_cache(cache_dir=cache_dir, device=device, max_length=max_length)
        if provider.identity.synthetic:
            raise ValueError("Cached model factory returned a synthetic identity")
        instance = cls.__new__(cls)
        instance._initialize(provider, acceptance_threshold, minimum_margin, max_calls, time.monotonic)
        instance.load_latency_ms = round((time.monotonic() - started) * 1000, 3)
        return instance

    @classmethod
    def for_test(cls, encoder, **kwargs) -> LocalOpenJevProvider:
        """Exercise the real package mapping with a synthetic, offline encoder."""
        return cls(provider=OpenJevProvider(encoder, synthetic=True), **kwargs)

    def decide(self, state: str, choices: tuple[str, ...], operation_id: str,
               timeout_seconds: float = 5.0) -> JevDecision:
        started = self._clock()
        identity = self._provider.identity
        metrics = {
            "calls": 0, "dispatches": 0, "api_requests": 0,
            "input_tokens": None, "output_tokens": None,
            "token_measurement": "not_exposed_by_package_encoder",
            "estimated_usd": "0", "actual_paid_usd": "0", "actual_paid_api_usd": "0",
            "provider_reported_cost_usd": None, "actual_billed_usd": None,
            "reserved_usd": "0", "reservation_held_usd": "0",
            "cost_basis": "local_inference_api_cost_only_excludes_hardware_and_electricity",
            "energy_joules": None, "energy_measurement": "not_measured",
            "latency_ms": 0.0, "load_latency_ms": self.load_latency_ms,
            "backend": "alexwortega-openjev-local", "repository": REPOSITORY,
            "checkpoint": CHECKPOINT, "revision": REVISION,
            "provider_identity": identity.model_dump(mode="json"),
            "score_semantics": "independent_entailment", "confidence_calibrated": False,
            "acceptance_threshold": self.acceptance_threshold, "minimum_margin": self.minimum_margin,
            "observations_simulated": True, "local_inference": not self.simulated,
        }

        def result(status, reason, choice=None):
            metrics["latency_ms"] = round(max(0, self._clock() - started) * 1000, 3)
            metrics["local_inference"] = not self.simulated and metrics["dispatches"] > 0
            # An entailment score is not hosted Jev categorical confidence.
            return JevDecision(choice, status, reason, None, self.model, operation_id,
                               self.simulated, dict(metrics))

        if (not isinstance(state, str) or not state.strip() or len(state.encode()) > MAX_STATE_BYTES
                or not isinstance(choices, tuple) or not 1 <= len(choices) <= len(ACTION_HYPOTHESES)
                or any(type(item) is not str or item not in ACTION_HYPOTHESES for item in choices)
                or len(set(choices)) != len(choices) or not isinstance(operation_id, str)
                or re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", operation_id) is None
                or type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= 30):
            return result("blocked", "invalid_request")
        try:
            raw = json.loads(state)
            if (not isinstance(raw, dict) or raw.get("health") not in _HEALTH
                    or type(raw.get("local_alarm")) is not bool
                    or type(raw.get("water_threshold_exceeded")) is not bool
                    or raw.get("simulated") is not True or raw.get("actuation_enabled") is not False):
                return result("blocked", "invalid_controller_state")
        except (ValueError, TypeError):
            return result("blocked", "invalid_controller_state")

        # Only engineered controller facts enter NLI. Raw sensor numbers,
        # evaluation labels and arbitrary text cannot become hidden instructions.
        facts = {"local_alarm": raw["local_alarm"],
                 "water_threshold_exceeded": raw["water_threshold_exceeded"],
                 "passive_monitoring_permitted": "continue_monitoring" in choices}
        health_text = {"fresh": "fresh observations", "missing": "missing observations",
                       "stale": "stale observations", "unsupported": "unsupported observations",
                       "conflicting": "conflicting observations"}[raw["health"]]
        alarm_text = "a latched alarm" if raw["local_alarm"] else "no latched alarm"
        monitoring_text = "permitted" if "continue_monitoring" in choices else "not permitted"
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(seconds=timeout_seconds)
        if expiry <= now:
            return result("blocked", "deadline_expired")
        request = DecisionRequest(
            request_id=operation_id,
            question=("Select a permitted supervisory label from these local-controller facts. "
                      "All observations and choices describe a simulation with no physical motion. "
                      "Numeric thresholds, observation freshness and alarm persistence are decided by local code. "
                      f"The controller reports {health_text} and {alarm_text}. "
                      f"Passive monitoring is {monitoring_text} by local policy."),
            created_at=now, valid_until=expiry,
            observations=tuple(Observation(
                observation_id=name, source="relay-local-controller", feature=name,
                value=float(value), unit="bool", observed_at=now, valid_until=expiry,
            ) for name, value in facts.items()),
            choices=tuple(ActionChoice(name=name, hypothesis=ACTION_HYPOTHESES[name]) for name in choices),
        )
        metrics["request_sha256"] = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
        metrics["hypothesis_count"] = len(choices)
        if not self._lock.acquire(blocking=False):
            return result("blocked", "local_inference_busy")
        try:
            if self._closed:
                return result("blocked", "local_provider_closed")
            if operation_id in self._seen:
                return result("blocked", "duplicate_operation")
            if self.calls >= self.max_calls:
                return result("blocked", "local_request_budget_exhausted")
            if self._clock() - started >= timeout_seconds:
                return result("blocked", "deadline_expired")
            self._seen.add(operation_id)
            self.calls += 1
            metrics["calls"] = 1
            previous_forwards = self._encoder_guard.forward_calls
            def before_compute():
                if self._clock() - started >= timeout_seconds:
                    raise _LocalDeadline("Deadline reached before native inference")
            self._encoder_guard.before_compute = before_compute
            failure = None
            try:
                output = self._provider.infer((request,))
                if not isinstance(output, tuple) or len(output) != 1:
                    failure = ("failed", "invalid_local_result")
                else:
                    answer = ProviderResult.model_validate(output[0].model_dump())
            except _ContextOverflow:
                failure = ("blocked", "input_context_exceeds_model_limit")
            except _LocalDeadline:
                failure = ("blocked", "deadline_expired")
            except Exception:
                failure = ("failed", "local_inference_failure")
            finally:
                metrics["dispatches"] = self._encoder_guard.forward_calls - previous_forwards
                metrics.update(self._encoder_guard.measurement)
                self._encoder_guard.before_compute = None
            if failure is not None:
                return result(*failure)
            if self._clock() - started >= timeout_seconds:
                return result("failed", "deadline_expired")
            if (answer.request_id != operation_id or answer.identity != identity
                    or answer.semantics != "independent_entailment"
                    or set(answer.scores) != set(choices) or answer.proposed_action not in choices
                    or answer.parameters or answer.evidence != "sufficient"):
                return result("failed", "invalid_local_result")
            metrics["entailment_scores"] = dict(answer.scores)
            metrics["nli_scores"] = {name: row.model_dump() for name, row in answer.nli_scores.items()}
            score = answer.scores[answer.proposed_action]
            others = [value for name, value in answer.scores.items() if name != answer.proposed_action]
            margin = score - max(others) if others else None
            metrics["selected_entailment"] = score
            metrics["selected_margin"] = margin
            if score < self.acceptance_threshold or (margin is not None and margin < self.minimum_margin):
                return result("blocked", "insufficient_nli_support")
            return result("completed", "local_nli_choice", answer.proposed_action)
        finally:
            self._lock.release()

    def close(self):
        """Prevent new work; does not claim to cancel already-running compute."""
        with self._lock:
            self._closed = True
