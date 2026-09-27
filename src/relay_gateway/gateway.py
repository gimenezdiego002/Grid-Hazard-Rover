"""Event-triggered inspection gateway; all outputs are findings, never commands."""

from decimal import Decimal
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from pollard import (Budget, BudgetExceeded, MissingRecording, Runtime, SQLiteStore,
                     recompute_charges, verify)
from pollard.meters import StepMeter, TokenMeter

from .budgeting import ConservativeUsdMeter, PayloadEstimator
from .models import Finding, Scenario, normalize_reference_context
from .providers import MAX_OUTPUT_TOKENS, MockProvider, make_payload
from .integrations.ledger import DispatchDenied, SpendBudgetExceeded


SESSION_API_CEILING_USD = Decimal("15.00")
USER_RESERVE_USD = Decimal("5.00")


def _open_store(path, replay):
    # Remote stores are opt-in: merely having a Mongo URI in the environment does
    # not cause a default mock run to connect to external infrastructure.
    if path == "mongodb":
        from pollard import MongoStore
        return MongoStore(os.environ["POLLARD_MONGODB_URI"],
                          database=os.environ.get("POLLARD_MONGODB_DATABASE", "relay"),
                          store_id=os.environ.get("POLLARD_STORE_ID", "relay-hackathon"),
                          collection_prefix=os.environ.get("POLLARD_MONGODB_PREFIX", "pollard"),
                          create=not replay, timeoutMS=10_000)
    target = Path(path or os.environ.get("RELAY_STORE_PATH", ".state/governance.sqlite"))
    if not replay:
        target.parent.mkdir(parents=True, exist_ok=True)
    return SQLiteStore(target, read_only=replay)


def _money(value):
    return format(Decimal(str(value)).quantize(Decimal("0.000001")), "f")


def _needs_review(reason):
    return Finding(status="needs_review", hazard_type=None, confidence_milli=0,
                   summary=reason, recommended_action="Keep the local alert visible and request human review.")


def _evaluation(scenario, findings):
    if any(obs.ground_truth_hazard is None for obs in scenario.observations):
        return {"available": False}
    episodes = []
    for obs in scenario.observations:
        if obs.ground_truth_hazard and (not episodes or episodes[-1][1] is not None):
            episodes.append([obs.timestamp_seconds, None])
        if not obs.ground_truth_hazard and episodes and episodes[-1][1] is None:
            episodes[-1][1] = obs.timestamp_seconds
    detections = [f["timestamp_seconds"] for f in findings if f["status"] == "suspected_hazard"]
    latencies = []
    for start, end in episodes:
        matching = [time for time in detections if time >= start and (end is None or time < end)]
        if matching:
            latencies.append(min(matching) - start)
    by_id = {obs.event_id: obs for obs in scenario.observations}
    return {"available": True, "labeled_hazard_episodes": len(episodes),
            "detected_hazard_episodes": len(latencies), "detection_latency_seconds": latencies,
            "false_positive_findings": sum(not by_id[f["event_id"]].ground_truth_hazard
                                           for f in findings if f["status"] == "suspected_hazard"),
            "scope": "Deterministic labeled simulation only; not real-world accuracy."}


def run_scenario(scenario: Scenario | dict, strategy="economy", *, provider=None,
                 store_path=None, replay=False, reference_context=None) -> dict:
    """Run a bounded inspection. Default stays offline even when API keys exist.

    Same mission/events in the same store reuse their recordings. New physical
    observations need new event IDs/timestamps; there is no cross-observation cache.
    """
    scenario = Scenario.model_validate(scenario)
    references = normalize_reference_context(reference_context)
    reference_ids = {document["reference_id"] for document in references}
    if strategy not in {"economy", "baseline"}:
        raise ValueError("Unknown strategy")
    provider = MockProvider() if provider is None else provider
    runtime = Runtime(_open_store(store_path, replay),
                      meters=[StepMeter(), TokenMeter(PayloadEstimator(),
                                                     reserved_output_tokens=MAX_OUTPUT_TOKENS),
                              ConservativeUsdMeter()],
                      mode="replay" if replay else "hybrid", refuse_duplicate_recordings=True)
    findings, events = [], []
    spend_operation_ids = []
    active_alerts: dict[str, bool] = {}
    calls_before = provider.calls
    stopped = False
    session_label = "relay-hackathon-live-v1" if provider.mode == "gemini" else "relay-hackathon-mock-v1"
    try:
        with runtime.run(session_label, budget=Budget(usd=SESSION_API_CEILING_USD)) as session:
            session.note({"mission_id": scenario.mission_id, "station_id": scenario.station_id,
                          "strategy": strategy, "budget": scenario.budget.model_dump(mode="json")})
            budget = Budget(steps=scenario.budget.max_requests, tokens=scenario.budget.max_tokens,
                            usd=scenario.budget.max_usd)
            with session.branch(budget=budget) as mission:
                branch_id = mission.cursor_id
                for observation in scenario.observations:
                    known_water = observation.kind == "water" and observation.value_milli is not None
                    value = observation.value_milli or 0
                    alarm = known_water and value >= 700
                    already_active = active_alerts.get(observation.robot_id, False)
                    reset = known_water and value <= 200 and already_active
                    if known_water and value <= 200:
                        active_alerts[observation.robot_id] = False
                    analyze = strategy == "baseline" or not known_water or (alarm and not already_active)
                    reason = ("fixed_interval" if strategy == "baseline" else
                              "unsupported_sensor_requires_review" if not known_water else
                              "threshold_crossing" if analyze else
                              "alert_reset" if reset else
                              "alert_already_active" if already_active else "below_threshold")
                    if alarm:
                        active_alerts[observation.robot_id] = True
                    event = {"event_id": observation.event_id, "timestamp_seconds": observation.timestamp_seconds,
                             "decision": "analyze" if analyze else "suppressed", "reason": reason,
                             "local_alarm": active_alerts.get(observation.robot_id, False)}
                    events.append(event)
                    if not analyze:
                        continue
                    if stopped:
                        finding = _needs_review("AI analysis paused after budget or provider failure.")
                    else:
                        payload = make_payload(provider, scenario.station_id, observation.evidence(),
                                               references, mission_id=scenario.mission_id)
                        try:
                            node = mission.model_call(payload, fn=provider)
                            operation_id = node.result.get("shared_spend_operation_id")
                            if operation_id:
                                spend_operation_ids.append(operation_id)
                            try:
                                finding = Finding.model_validate_json(node.result["text"])
                                if not set(finding.cited_reference_ids).issubset(reference_ids):
                                    raise ValueError("Finding cites unavailable reference IDs")
                            except (ValueError, KeyError, TypeError):
                                finding = _needs_review("Provider returned an invalid structured finding.")
                                stopped = True
                        except (BudgetExceeded, SpendBudgetExceeded):
                            finding = _needs_review("Mission or session AI budget refused this analysis.")
                            event["reason"] = "budget_refused"
                            stopped = True
                        except DispatchDenied:
                            finding = _needs_review("This external operation already exists; reconcile its recorded result before retrying.")
                            event["reason"] = "duplicate_external_operation"
                            stopped = True
                        except MissingRecording:
                            finding = _needs_review("Strict replay has no recording for this observation.")
                            event["reason"] = "missing_recording"
                            stopped = True
                        except Exception:
                            # No native exception text: SDK exceptions can contain request data.
                            finding = _needs_review("Provider or accounting failed; no automatic retry was attempted.")
                            event["reason"] = "provider_or_accounting_failure"
                            stopped = True
                    findings.append({"event_id": observation.event_id,
                                     "timestamp_seconds": observation.timestamp_seconds,
                                     **finding.model_dump()})
                charges = recompute_charges(runtime.store, branch_id)
                avoided = mission.report()["avoided"]
                session_charges = session.report()["spent"]
                integrity = verify(runtime.store, mission.cursor_id)
                new_calls = provider.calls - calls_before
                estimated_usd = charges.get("usd", 0)
                new_estimated_usd = max(Decimal(0), Decimal(str(estimated_usd))
                                        - Decimal(str(avoided.get("usd", 0))))
                return {
                    "mission_id": scenario.mission_id, "strategy": strategy,
                    "provider_mode": provider.mode,
                    "simulated": provider.mode == "mock" or scenario.simulated,
                    "actuation_enabled": False, "root_id": session.root_id,
                    "findings": findings, "events": events,
                    "reference_context": [{key: value for key, value in document.items() if key != "body"}
                                          for document in references],
                    "outcome": "needs_review" if any(f["status"] == "needs_review" for f in findings) else "complete",
                    "accounting": {
                        "requests": int(charges.get("steps", 0)), "new_requests": new_calls,
                        "tokens": int(charges.get("tokens", 0)),
                        "estimated_usd": _money(estimated_usd),
                        "new_estimated_usd": _money(new_estimated_usd),
                        "actual_paid_usd": "0.000000" if provider.mode == "mock" else None,
                        "replayed_requests": int(avoided.get("steps", 0)),
                        "avoided_tokens": int(avoided.get("tokens", 0)),
                        "session_estimated_usd": _money(session_charges.get("usd", 0)),
                        "shared_spend_operation_ids": list(dict.fromkeys(spend_operation_ids)),
                        "price_basis": "illustrative simulation rates" if provider.mode == "mock" else "operator-supplied model rates; invoice authoritative",
                    },
                    "limits": {**scenario.budget.model_dump(mode="json"),
                               "session_api_ceiling_usd": "15.00", "reserve_usd": "5.00"},
                    "evaluation": _evaluation(scenario, findings),
                    "audit_verified": integrity.ok,
                    "limitations": ["No physical robot commands or media decoding.",
                                    "Estimated token/USD reservations can differ from final provider usage.",
                                    "No cloud energy or carbon measurement; no whole-account spending enforcement."],
                }
    finally:
        close = getattr(runtime.store, "close", None)
        if close:
            close()


def compare_scenario(scenario: Scenario | dict) -> dict:
    """Same observations, actual mock/Pollard paths, fresh ledgers for both policies."""
    scenario = Scenario.model_validate(scenario)
    with TemporaryDirectory(prefix="relay-compare-") as directory:
        baseline = run_scenario(scenario, "baseline", store_path=Path(directory) / "baseline.sqlite")
        economy = run_scenario(scenario, "economy", store_path=Path(directory) / "economy.sqlite")
    base = baseline["accounting"]
    eco = economy["accounting"]
    avoided_requests = base["requests"] - eco["requests"]
    return {"simulated": True, "actual_paid_usd": "0.000000", "baseline": baseline, "economy": economy,
            "savings": {"requests_avoided": avoided_requests,
                        "tokens_avoided": base["tokens"] - eco["tokens"],
                        "estimated_usd_avoided": _money(Decimal(base["estimated_usd"]) - Decimal(eco["estimated_usd"])),
                        "request_reduction_percent": round(100 * avoided_requests / base["requests"], 2) if base["requests"] else 0},
            "comparison_complete": baseline["outcome"] == economy["outcome"] == "complete",
            "environmental_claim": "Fewer simulated model requests and tokens. No measured energy or carbon savings."}
