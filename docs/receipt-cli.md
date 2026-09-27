# One report receipt on Solana devnet

The receipt command makes the existing adapter executable without changing the mock dashboard. It creates a local mock receipt by default, or verifies a supplied receipt file read-only. Mock mode never reads environment settings, wallet state or the spending ledger, and makes no network request. Neither mode controls hardware.

Use a UTF-8 JSON report with an explicit Boolean `simulated` field, or the existing completed mock integration replay containing its `report`. Files are limited to 256 KiB, nesting to 20 levels, and duplicate keys/non-finite numbers are refused. Loading a saved replay validates its format; it does not authenticate the file's claims. Creation requires explicit finalization of the exact report and never changes its human-review fields.

```powershell
.\.venv\Scripts\python.exe -m relay_gateway.integrations.receipt_cli create --report-file artifacts/integration-replay.json --finalized | Set-Content -Encoding utf8 artifacts/receipt-proof.json
.\.venv\Scripts\python.exe -m relay_gateway.integrations.receipt_cli verify --report-file artifacts/integration-replay.json --receipt-file artifacts/receipt-proof.json
```

The first output contains a receipt descriptor; the second reports `mock_hash_verified`. This is local hash consistency only. A modified copy of the report returns `report_changed` and `valid: false`, with no network call. Verification accepts either a direct adapter receipt or the creation command's JSON envelope.

## Explicit live operation

Live operations require both `--live` and `RELAY_ALLOW_SOLANA_DEVNET=1`. The adapter supports only the fixed public devnet endpoint. There are no command-line options for a custom endpoint, wallet, state directory, network or funding. It uses the project-root `.state/solana/devnet-keypair.json` regardless of the launch directory. If absent, the existing adapter creates a protected dedicated devnet key; it never imports another wallet. No private key bytes appear in output.

The existing dedicated wallet currently has no test-token funding. A live creation attempt would stop after the bounded balance/fee checks without sending a transaction. This command never calls a faucet or buys tokens. Arrange authorized devnet funding separately before attempting receipt proof; do not repeat the previously rejected faucet attempt automatically.

After funding is verified, an operator can deliberately create one receipt:

```powershell
$env:RELAY_ALLOW_SOLANA_DEVNET = '1'
.\.venv\Scripts\python.exe -m relay_gateway.integrations.receipt_cli create --report-file artifacts/integration-replay.json --finalized --live | Set-Content -Encoding utf8 artifacts/receipt-proof.json
```

The adapter estimates the fee, checks balance, saves the signature before submission, submits once with preflight enabled and retries disabled, and checks confirmation once. The fee estimate is in **devnet lamports: test-token units, not USD**. This command does not convert that estimate to money, claim a reconciled provider invoice, or initialize/reset/mutate the cumulative spending ledger. Live `actual_billed_usd` remains null. Introducing a paid RPC service would require separate reviewed metering and is unsupported by this command.

A pending confirmation returns `not_yet_confirmed`; timeout or uncertain creation is reported as `unknown`. Inspect the saved receipt before recovery. The canonical adapter record is `.state/solana/receipts/<report-sha256>.json`; an uncertain send may have saved this record even when the command's output contains only an error. Never delete its signature record to force a retry. Repeating creation for the identical report consults the saved signature and cannot submit a second transaction. The command adds no retries, resubmission loop or automatic polling.

Verify a pending receipt later with one explicit read-only call:

```powershell
.\.venv\Scripts\python.exe -m relay_gateway.integrations.receipt_cli verify --report-file artifacts/integration-replay.json --receipt-file artifacts/receipt-proof.json --live
```

If the saved command output is an error rather than a receipt, provide the canonical adapter receipt file instead. Verification never creates a wallet, alters the receipt file or submits a transaction. Without `--live`, a live receipt returns `chain_not_checked` and `valid: null`; a matching local hash does not establish chain proof. With live verification, the adapter checks transaction execution, signer, signature and exact memo digest. Only `confirmed` with `chain_verified: true` is chain proof. It proves report integrity, not sensor accuracy or physical inspection.

Output allowlists receipt and verification fields; it never copies arbitrary provider errors or saved-record fields. The devnet explorer URL is constructed from the validated public signature. Exit code 0 means mock creation, a valid mock hash check, or confirmed chain evidence; pending, changed, failed or unresolved outcomes return 2. Preserve synthetic-data labels throughout the demonstration.

Tests use fake adapters/transports and temporary files, with sockets prohibited:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_receipt_cli.py tests/test_audio_receipt.py -q
```

The adapter's existing tests cover SDK signing, saved-signature reuse and uncertain-send protection. The command tests cover bounded input, explicit live gating, canonical state anchoring, read-only verification, status handling and redaction. Passing these tests does not fund a wallet or establish a real devnet transaction.
