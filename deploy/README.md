# Relay deployments

GCP is the primary cloud. Actual resource status, budget and lifetime are in [cloud setup](../docs/cloud-setup.md). DigitalOcean's separate device gateway is documented in [digitalocean.md](digitalocean.md).

The deployed Cloud Run service is private and mock-only. From the authenticated laptop, run:

```powershell
gcloud run services proxy relay-gateway --region=us-east1 --project=shellhacks-relay-2026-0926 --port=8766
```

Then open `http://127.0.0.1:8766`. Direct unauthenticated access to its run.app URL returns 403. The ordinary local dashboard remains at `http://127.0.0.1:8765`.

## Rebuild deliberately

Check the canonical shared ledger and existing GCP reservation before another build. `.gcloudignore` and `.dockerignore` allowlist only application files. Inspect `gcloud meta list-files-for-upload` before uploading: no `.state`, `.env`, key, credential, ledger or virtual-environment files may appear.

```powershell
gcloud builds submit --config=deploy/cloudbuild.yaml --substitutions=_IMAGE=us-east1-docker.pkg.dev/shellhacks-relay-2026-0926/relay/relay-gateway:demo --service-account=projects/shellhacks-relay-2026-0926/serviceAccounts/relay-build@shellhacks-relay-2026-0926.iam.gserviceaccount.com --gcs-source-staging-dir=gs://shellhacks-relay-2026-0926-build/source --project=shellhacks-relay-2026-0926 --region=us-east1 --async
```

Wait for a successful build, inspect its returned image digest, and deploy that digest. Keep `--no-allow-unauthenticated`, the dedicated `relay-runtime` identity, minimum zero, maximum one, request-based CPU, and `RELAY_ALLOW_LIVE_GEMINI=0`. Do not inject provider secrets into the mock container. Private invocation, instance limits and provider billing alerts are not dollar hard stops.

Record the deployed revision, build and digest in `.state/cloud-config.json`, then run `.\.venv\Scripts\python.exe scripts/verify-cloud.py` for a finite authenticated smoke check under the existing GCP reservation. It checks private access, mock integration replay, directed mission review, and budget-refusal behavior, without exposing its identity token. A successful run updates `artifacts/cloud-verification.json`. The cloud mission engine uses bounded process memory, so a container restart clears mission records.

## End the demo

Review lifetime by September 28, 2026. To stop serving the demo, after checking it is no longer needed:

```powershell
gcloud run services delete relay-gateway --region=us-east1 --project=shellhacks-relay-2026-0926
```

This does not delete retained images, secrets, or buckets. Review those project-specific resources and preserve needed evidence before removing them. Do not delete unrelated projects or release the shared reservation before billing is reconciled. No automatic shutdown has been scheduled.

If other vendors are provisioned later, record their exact task-only resources and shutdown times. Delete a paid DigitalOcean service to end its charges; stopping a process or powering off a Droplet is insufficient. Suspend Snowflake compute between deliberate operations, and separately account for any continuous services. Preserve historical spending if changing stores. Credentials never belong in images, source control, browser code, or terminal output.
