"""Finite authenticated smoke check of Relay's private mock deployment.

Run deliberately under the existing GCP resource reservation. Identity tokens
stay in memory; only non-secret, selected evidence is saved or printed.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPRedirectHandler
from uuid import uuid4


PROJECT = "shellhacks-relay-2026-0926"
REGION = "us-east1"
SERVICE = "relay-gateway"
ORIGIN = "https://relay-gateway-345149168663.us-east1.run.app"
ROOT = Path(__file__).resolve().parents[1]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def cloud(*args):
    executable = shutil.which("gcloud")
    if not executable:
        raise RuntimeError("gcloud is unavailable")
    result = subprocess.run([executable, *args, f"--project={PROJECT}", "--quiet"],
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError("gcloud check failed; diagnostic output withheld")
    return result.stdout.strip()


def main():
    # The ledger is read, never reinitialized with a new budget or settled here.
    from relay_gateway.integrations.ledger import SpendLedger
    ledger = SpendLedger().snapshot()
    reservation = next((op for op in ledger["operations"]
                        if op["operation_id"] == "gcp-demo-resources-2026-09-26"), None)
    if not reservation or reservation["status"] != "dispatched":
        raise RuntimeError("Existing GCP reservation is unavailable; review spending first")

    prior_path = ROOT / ".state" / "cloud-config.json"
    evidence = json.loads(prior_path.read_text(encoding="utf-8"))
    expected_revision = evidence["revision"]
    assert evidence["project_id"] == PROJECT and evidence["url"] == ORIGIN

    def verify_traffic():
        service = json.loads(cloud("run", "services", "describe", SERVICE,
                                   f"--region={REGION}",
                                   "--format=json(status.latestReadyRevisionName,status.traffic)"))
        status = service["status"]
        traffic = status["traffic"]
        assert status["latestReadyRevisionName"] == expected_revision
        assert sum(item.get("percent", 0) or 0 for item in traffic
                   if item.get("revisionName") == expected_revision) == 100
        assert not any((item.get("percent", 0) or 0) > 0 for item in traffic
                       if item.get("revisionName") != expected_revision)
        return {"revision": expected_revision, "percent": 100}

    traffic_before = verify_traffic()
    token = cloud("auth", "print-identity-token")
    opener = build_opener(NoRedirect())

    def request(path, data=None, *, authenticated=True):
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = "Bearer " + token
        req = Request(ORIGIN + path, headers=headers,
                      data=None if data is None else json.dumps(data).encode())
        try:
            with opener.open(req, timeout=30) as response:
                body = response.read(2_000_001)
                if len(body) > 2_000_000:
                    raise RuntimeError("Oversize response")
                return response.status, json.loads(body)
        except HTTPError as exc:
            return exc.code, None

    def checked(path, data=None):
        status, body = request(path, data)
        if status != 200:
            raise RuntimeError(f"Unexpected HTTP {status} at {path}")
        return body

    unauthenticated, _ = request("/health", authenticated=False)
    assert unauthenticated == 403
    health = checked("/health")
    assert health["provider_mode"] == "mock" and not health["paid_api_enabled"]
    assert not health["actuation_enabled"]
    inventory = checked("/api/missions/inventory")
    assert inventory["simulated"] and not inventory["physical_connections_verified"]

    replay = checked("/api/integrations/demo", {})
    steps = {step["provider"]: step for step in replay["steps"]}
    assert replay["status"] == "completed" and replay["network_requests"] == 0
    assert len(steps) == 6 and steps["tiger"]["evidence"]["readback_events"] == 12

    mission_results = []
    for outcome in ("suspected_hazard", "budget_refused"):
        mission_id = "cloud-proof-" + uuid4().hex[:16]
        planned = checked("/api/missions", {"mission_id": mission_id,
                          "action_id": "create", "mode": "directed",
                          "target_id": "synthetic-north-door", "second_view": True})
        assert planned["simulated"] and not planned["actuation_enabled"]

        def act(action, payload=None, action_id=None):
            return checked(f"/api/missions/{mission_id}/actions", {
                "action_id": action_id or action, "action": action,
                "payload": payload or {}})

        assert act("start")["status"] == "running"
        assert act("pause")["status"] == "paused"
        assert act("resume")["status"] == "running"
        act("complete_task", {"task_id": "monitor", "outcome": "completed"}, "monitor")
        if outcome == "budget_refused":
            fixture = checked("/scenarios/leak.json")
            fixture["budget"]["max_requests"] = 0
            denied = checked("/api/run", {"scenario": fixture, "strategy": "economy"})
            assert denied["accounting"]["new_requests"] == 0
            assert any(event["reason"] == "budget_refused" for event in denied["events"])
        observed = act("complete_task", {"task_id": "scout", "outcome": outcome}, "scout")
        assert observed["status"] == "needs_review"
        reviewed = act("simulate_review", {"decision": "acknowledge"})
        if outcome == "suspected_hazard":
            assert reviewed["status"] == "running"
            result = act("complete_task", {"task_id": "announce", "outcome": "completed"}, "announce")
            assert result["status"] == "completed"
        else:
            result = reviewed
            assert result["status"] == "needs_review" and result["budget_refused"]
            assert "complete_task" not in result["allowed_actions"]
        assert result["environment_safety"] == "not_established"
        assert not result["review"]["human_review_performed"]
        mission_results.append({"input_outcome": outcome, "final_status": result["status"],
                                "progress": result["progress"], "simulated": True,
                                "human_review_performed": False, "actuation_enabled": False})

    traffic_after = verify_traffic()
    revision = expected_revision
    evidence.update({"verified_at": datetime.now(timezone.utc).isoformat(),
                     "unauthenticated_status": unauthenticated, "health": health,
                     "cloud_missions": mission_results,
                     "verified_traffic_before": traffic_before,
                     "verified_traffic_after": traffic_after,
                     "deployment_status": "deployed_and_verified_private",
                     "cloud_replay": {"status": replay["status"], "steps": len(steps),
                                      "telemetry_rows": 12, "network_requests": 0}})
    receipt = steps["solana"]["evidence"]
    assert receipt["original_valid"] and not receipt["modified_valid"]
    assert not receipt["chain_verified"] and receipt["transaction_signature"] is None
    evidence["cloud_replay"]["receipt_checks"] = receipt
    encoded = json.dumps(evidence, indent=2) + "\n"
    prior_path.write_text(encoded, encoding="utf-8")
    (ROOT / "artifacts" / "cloud-verification.json").write_text(encoded, encoding="utf-8")
    print(json.dumps({"status": "verified", "revision": revision,
                      "private_http_status": unauthenticated, "mock_stages": len(steps),
                      "mission_results": mission_results}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # No raw provider response, HTTP header, subprocess stderr or token.
        print(f"Cloud verification stopped ({type(exc).__name__}); no success evidence saved.", file=sys.stderr)
        raise SystemExit(1) from None
