# Offline rehearsal packet

Run from the repository with its installed project-local environment:

```powershell
.\.venv\Scripts\python.exe scripts\rehearse-demo.py
```

The command prints paths to `packet.json` and `index.html` in a new unique directory below `artifacts/rehearsal`. Open that HTML file directly for a readable fallback when the dashboard or internet is unavailable. It contains the comparison, mission outcomes, checks, proof limits and expandable complete evidence; it needs no scripts or remote assets. Every run preserves earlier packets and unrelated files. Use `--output-dir PATH` to choose a different parent directory.

The fixed input is `scenarios/leak.json`, a bounded twelve-reading synthetic water fixture. Its SHA-256 is recorded in the packet. There is no arbitrary fixture input or live mode. The script calls the existing mission engine, gateway with an explicit mock provider and temporary local recordings, comparison function and six-adapter mock workflow. It does not need a server, inspect credentials, construct the live spending ledger, or contact services.

The checks derive from actual returned results, including:

- Preset and directed missions finish only after the simulated review transition; unavailable optional second observations are skipped.
- The zero-request analysis makes zero calls, keeps the local alarm and remains `needs_review` after acknowledgement. An announcement attempt is rejected without mutating state.
- Both comparison policies detect the single labeled synthetic incident. The baseline uses 12 mock calls and economy uses 1; the packet shows the resulting simulated tokens and costs.
- All six mock adapter stages finish; telemetry replay inserts no duplicates, the report reads back, findings cite retrieved references and local receipt verification rejects a modified report.
- No returned evidence claims hardware actuation, human approval, audio generation, a blockchain transaction or remote provider verification.

Exit status `0` means every recorded check passed. A failed check produces a packet marked `failed` and exit status `1`; an execution or fixture error exits `1` without claiming a successful packet. Do not present an older saved packet as evidence that the latest attempt passed. The generator uses explicit checks, so Python optimization does not disable validation.

Every packet is simulation evidence. No physical inspection, cloud integration, sponsor qualification, model quality, energy, carbon, battery-life or water saving is established by it. Review [MLH integration status](mlh-integrations.md) and separate saved provider evidence for actual connection claims. Actual new paid API charges from this command are zero, while existing cloud resources may still accrue charges under the shared budget. The command does not read or update the canonical spending ledger.
