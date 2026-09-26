# DigitalOcean fleet intake deployment

The reviewable App Platform spec is [deploy/digitalocean-fleet.yaml](../deploy/digitalocean-fleet.yaml). It uses JSON syntax, which is valid YAML, so the existing Python standard library can prepare an API payload without another dependency. It is a deployment proposal; this file alone is not evidence of a deployed service.

The service runs the existing `relay_gateway.fleet_gateway:app` from the public [Grid-Hazard-Rover repository](https://github.com/gimenezdiego002/Grid-Hazard-Rover), branch `relay/inspection-system`, with the root Dockerfile and a fleet-only run-command override. GCP remains the primary Relay cloud. This component provides authenticated short-term telemetry intake; it does not replace the teammate backend, invoke a model, forward automatically to a database, or control robots. The existing [gateway contract](../deploy/digitalocean.md) and [finite consumer](fleet-consumer.md) still apply.

## Fixed deployment settings

| Setting | Prepared value |
|---|---|
| App/component | `relay-fleet-2026-0926` / `fleet-intake` |
| Region | `nyc` |
| Size/count | `apps-s-1vcpu-0.5gb`, exactly 1 instance, 1 shared CPU, 512 MiB |
| Execution | One Uvicorn worker, `0.0.0.0:8080`, root route `/` |
| Health | Public `GET /health`; telemetry and event reads require a bearer token |
| Retention | Process memory, 5,000 events, 3,600-second TTL |
| Lifetime | At most 24 hours from creation; record the exact UTC deletion deadline |
| Reservation | $1 in the existing canonical shared ledger before creation |
| Extras | No database, worker, scheduled job, dedicated IP, autoscaling or custom domain |

The listed size is $5/month, billed per second with a $0.01 minimum. At the documented 28-day monthly basis, 24 hours of compute is approximately $0.18 before other charges; this is a planning estimate, not an invoice. Retain the $1 reservation until usage is reconciled, and count it with every earlier reservation against the existing $15 operating plan/$20 total authorization. Check the creation-screen quote; do not substitute a larger plan silently. [Official pricing](https://docs.digitalocean.com/products/app-platform/details/pricing/) and [billing basis](https://docs.digitalocean.com/platform/billing/bandwidth/).

## Public repository and creation paths

The prepared spec uses `git.repo_clone_url` and `git.branch`. This source requires a repository cloneable without authentication; it avoids a GitHub integration requirement for this public source. The `git` object has no `deploy_on_push` field, so the spec does not install a push-triggered deployment setting. If the control panel converts the source to a `github` object, explicitly set `deploy_on_push: false`. Record the source commit SHA actually built; a branch name alone does not identify deployed code. [Source requirements](https://docs.digitalocean.com/reference/terraform/reference/resources/app/) and [app-spec reference](https://docs.digitalocean.com/products/app-platform/reference/app-spec/).

Two supported creation routes are available:

1. **API/CLI:** submit the prepared app object in `{"spec": ...}` to `POST https://api.digitalocean.com/v2/apps`, or use `doctl apps create --spec PATH` with a private prepared copy. API access needs an appropriately scoped DigitalOcean administrative token. Browser sign-in alone does not supply that token. Do not send the fleet bearer token as the administrative credential.
2. **Control panel:** open **Create → App Platform**, select the repository and `relay/inspection-system`, use the root source directory and Dockerfile, and clear **Autodeploy**. If the UI requires the GitHub integration, it requires repository access and the documented Owner/Maintainer role; use the public-git API route if that connection is unavailable. Configure the exact component settings above, run-command override, environment variables and $5 plan. Select the intended task project rather than modifying unrelated resources. Review the summary before creating the app. [Official creation instructions](https://docs.digitalocean.com/products/app-platform/how-to/create-apps/).

Do not claim that the public-git API route has been accepted by this account until an actual create response is recorded. Existing account membership, billing eligibility, available region, source visibility and successful image build remain deployment prerequisites.

## Runtime secret required before creation

The committed `RELAY_FLEET_API_TOKEN` value is deliberately empty. Replace that value **only in memory or the encrypted component runtime setting before creating the app**. Startup rejects an empty token. Use a fresh cryptographically random URL-safe secret, 32–512 characters, separate from all provider and administrative keys. Set its type to `SECRET` and scope to `RUN_TIME`; select **Encrypt** in the UI. No provider keys belong in this service. [Runtime secrets](https://docs.digitalocean.com/products/app-platform/how-to/use-environment-variables/).

For an API client, this prepares a request object without printing or writing the token:

```python
import json
import os
from pathlib import Path
import re

spec = json.loads(Path("deploy/digitalocean-fleet.yaml").read_text(encoding="utf-8"))
token = os.environ["RELAY_FLEET_API_TOKEN"]
if re.fullmatch(r"[A-Za-z0-9._~-]{32,512}", token) is None:
    raise ValueError("A valid fleet runtime token is required")
for setting in spec["services"][0]["envs"]:
    if setting["key"] == "RELAY_FLEET_API_TOKEN":
        setting["value"] = token
request_body = {"spec": spec}
# Supply request_body directly to the authenticated App Create API client.
# Do not log it, print it, save it in the repository, or dump the API app spec.
```

`RELAY_FLEET_MODE=live` enables remote authenticated transport. It does not enable model usage or hardware operation. Keep fixture envelopes `simulated: true`; the existing finite sender enforces this. Health remains public because App Platform uses it to check the service. The health field `cloud_deployment_verified` remains false by design: separate deployment evidence establishes hosting, rather than the application claiming it for itself.

## Finite verification and evidence

Before sending events, record the actual app ID, HTTPS origin, selected quote, source commit, deployment ID, creation timestamp and UTC deletion deadline. Obtain the canonical ledger snapshot and reserve the $1 lifetime before creating the app, not after successful verification. No reservation is created by reading this document.

1. Confirm deployed settings match the spec and readiness is healthy. Read `/health`: expect `role=fleet_telemetry_gateway`, `mode=live`, `auth_required=true`, `model_calls_enabled=false`, `actuation_enabled=false` and `durability=process_memory`.
2. Verify an unauthenticated `GET /events` and a valid unauthenticated `POST /telemetry` both return 401. Do not include credentials in saved HTTP evidence.
3. Set the local environment's fleet bearer token, obtain the actual origin from the app record, and run the finite sender once. It sends 13 synthetic station/rover envelopes and exits:

   ```powershell
   .\.venv\Scripts\python.exe -m relay_gateway.fleet_gateway send-fixture --scenario scenarios/leak.json --base-url $relayFleetOrigin --allow-remote
   ```

4. Run one authenticated consumer fetch. It makes one bounded GET, validates hashes and persists the cursor and synthetic evidence locally; it never runs inference:

   ```powershell
   .\.venv\Scripts\python.exe -m relay_gateway.fleet_consumer --url $relayFleetOrigin --fetch-live --allow-remote --limit 100
   ```

5. For the idempotency proof, deliberately send that same finite fixture once more: expect 13 duplicates with their original sequence numbers, then verify readback still contains 13 records. No background loops or retry until success. A gateway restart or expired retention can invalidate this expectation; record the changed stream/gap and follow the existing explicit consumer recovery procedure.

Save selected, credential-free evidence: health flags, auth response codes, fixture acknowledgements, authenticated consumer results, stream ID, source/deployment identifiers, verification time and app URL. These establish a DigitalOcean-hosted synthetic telemetry transport path only. They do not establish a physical robot connection or automatic GCP/database forwarding.

## Delete within the reserved lifetime

Export required consumer evidence before deletion. Delete **only the recorded Relay App Platform app** by its verified app ID through the control panel, `doctl apps delete APP_ID`, or `DELETE /v2/apps/APP_ID`. Verify its absence and reconcile the shared reservation using the provider's usage/billing evidence. Keep unknown charges reserved. Deleting this app does not authorize deleting other resources or changing GCP.

The spec contains no automatic destruction mechanism. A 24-hour note, reminder, health-check failure or stopped process is not a billing stop. The operator who creates the app must record and execute the deletion deadline; if no one can own that deadline, complete the finite proof and delete it immediately afterward.
