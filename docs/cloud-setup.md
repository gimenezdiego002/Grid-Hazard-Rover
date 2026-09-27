# ShellHacks Relay cloud setup

Verified on September 26, 2026. The user chose a separate project: `shellhacks-relay-2026-0926` (project number `345149168663`). Commands always name this project explicitly; the existing gcloud default and unrelated projects were not changed.

## Deployed and checked

| Resource | Evidence and scope |
|---|---|
| Cloud Run `relay-gateway`, `us-east1` | Private service at `https://relay-gateway-345149168663.us-east1.run.app`; unauthenticated health request returned 403; authenticated health and integration replay succeeded |
| Runtime configuration | Request-based CPU, 1 vCPU / 512 MiB, concurrency 1, minimum 0, revision maximum 1, 30-second request timeout; mock API only |
| Artifact Registry `relay` | Cloud Build produced and pushed the image; exact build, digest and revision are in `artifacts/cloud-verification.json` |
| Evidence bucket | `gs://shellhacks-relay-2026-0926-evidence`, uniform access, public access prevented; synthetic report uploaded and read back identically; objects expire after 7 days, soft delete disabled |
| Build staging bucket | `gs://shellhacks-relay-2026-0926-build`, private; source archives expire after 2 days, soft delete disabled |
| Secret Manager | `relay-gemini-api-key` contains a dedicated key restricted to the Gemini Developer API; no secret was attached to the mock Cloud Run service |
| Service identities | `relay-build` has the Cloud Run builder role plus read access to the staging bucket; `relay-runtime` has no added project roles |
| Native Gemini proof | A local guarded request using the new project's secret returned 275 tokens and a suspected-water finding on synthetic text; its usage estimate was rounded upward to $0.000257 in the shared ledger |

The cloud replay exercised six **mock** adapters and twelve synthetic readings. It made no calls to remote model, speech, database or blockchain APIs. Revision `relay-gateway-00006-w89` also passed the finite mission checks: directed rehearsal completed after explicit simulated review; a zero-request mission remained `needs_review` after simulated acknowledgement. The verification script checked 100% service traffic reached the expected revision before and after its requests. The latest update also verified the revision image digest, byte-identical served HTML/JavaScript, explicit mock environment settings, runtime limits and private invocation policy, and duplicate mission action receipts with current-state read-back. Build source commit and file hashes are recorded in `artifacts/cloud-build-source.json`. Mission records are bounded process memory and can disappear on a container restart. The hosted interface is not proof of physical inspection or all eight sponsor integrations.

During initial API-key creation, gcloud printed the key in operation diagnostics despite a format filter. That key (`relay-gemini`) was immediately revoked. Its replacement (`relay-gemini-private`) was created with stdout/stderr captured, and its value went directly into Secret Manager without a local secret file or terminal output. Keep all credential-returning gcloud commands captured, including stderr.

## Budget and lifetime

The canonical local shared ledger is `.state/spend.sqlite`. It contains the historical $0.000179 Gemini estimate, $0.000257 for the second call, and a **$3.00 unresolved GCP reservation**. Thus $3.000436 is committed and $11.999564 remains within the $15 planned envelope; the other $5 is still held. Actual billed totals are unknown. See `docs/current-spend.json` for the recorded snapshot, not an invoice.

The $3 reservation covers this short demo's build, storage, secrets and authenticated test traffic through **September 28, 2026**. Review or stop the deployment at that point before extending its lifetime. There is no automatic project shutdown. Cloud Run can scale to zero; retained images/secrets/storage may still charge. Lifecycle deletion can be delayed, so retain the reservation until charges are reconciled. Free tiers and credits have not been assumed available across the billing account.

Pricing references: [Cloud Run](https://cloud.google.com/run/pricing), [Cloud Build](https://cloud.google.com/build/pricing), [Artifact Registry](https://cloud.google.com/artifact-registry/pricing), [Gemini](https://ai.google.dev/gemini-api/docs/pricing).

## Remaining account work

MongoDB Atlas, Tiger Data, Snowflake, ElevenLabs and DigitalOcean have tested local implementations but no verified account credentials or live demonstration yet. MLH offer eligibility and an eligible GoDaddy Registry domain remain unverified. The dedicated Solana devnet wallet exists, but the one funding attempt was rejected and no transaction has been submitted. `docs/mlh-integrations.md` tracks each proof requirement.

The cloud service has no live switch accessible over HTTP. Enabling paid work in cloud replicas requires a durable shared spending store; the container's ephemeral SQLite file is not suitable for that purpose.
