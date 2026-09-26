# Reviewed briefings and report receipts

`relay_gateway.integrations.audio_receipt` implements two explicit adapters. Defaults are deterministic mocks and make no network requests. A mock briefing returns no audio file; a mock receipt is a local hash descriptor, never a fabricated transaction. The caller must reserve shared spending before dispatching live speech.

## ElevenLabs

The separate guarded CLI has completed one real generation from the reviewed 165-character synthetic demo script. [Sanitized evidence](../artifacts/elevenlabs-live-proof.json) records premade River / Eleven Flash v2.5, verified MP3 hashing and full decoding, 83 provider-defined usage units, and the retained $0.05 unknown-billing reservation. Audible semantic review, connected-report linkage and hardware playback remain unverified. The integrated replay remains mock-only.

Call `synthesize_briefing(text, reviewed=True)` for a mock, or use `live=True` after setting `RELAY_ALLOW_ELEVENLABS=1`, `ELEVENLABS_API_KEY`, and `ELEVENLABS_VOICE_ID`. `ELEVENLABS_MODEL_ID` is optional; the default is `eleven_multilingual_v2`. Keys are read only at dispatch and never stored in results.

The adapter uses the documented POST `/v1/text-to-speech/{voice_id}`, sends `xi-api-key` authentication, and requests `mp3_44100_128`. Text is capped at 600 characters, output at 4 MiB, and each network request at 20 seconds. It performs zero automatic retries. [ElevenLabs API reference](https://elevenlabs.io/docs/api-reference/text-to-speech/convert).

Returned MP3 files and hash metadata go in `.state/audio/`. The cache identity includes text, voice, model, and output format. Identical successful requests reuse the audio; changed voice/model/text produces a distinct entry. An exclusive lock prevents concurrent duplicate generation. A persisted dispatch marker blocks repeat charges after a timeout or incomplete write. Resolve its billing status before any manual recovery; deleting the marker is not routine retry handling. MP3 validation checks response type and signature, not a full audio decode.

The result records input characters, cache identity, audio path/hash, whether a request was sent, and optional provider request ID. It also allowlists `character-cost` as `provider_character_cost` (a nonnegative decimal string), and `x-trace-id` as `provider_trace_id` (a bounded identifier). No raw header map is saved. `provider_character_cost_status` is `reported`, `missing`, `malformed`, or `not_requested` for mocks. Missing or malformed values stay null; they never fall back to the input text length. [Official generation metadata headers](https://elevenlabs.io/docs/api-reference/introduction#tracking-generation-costs).

The official reference describes `character-cost` as character cost but does not establish a universal conversion to currency. `provider_character_cost_unit: "provider_defined"` deliberately preserves that distinction: this value is neither USD nor an assertion that one unit equals one raw input character or one account credit. The caller must verify the selected account/model/voice pricing and its usage-unit mapping before settling a reservation. A valid header alone does not establish billable USD. Actual billed USD remains null for every live result; this adapter never derives an estimate automatically. Unknown usage or pricing keeps the shared ledger reservation unresolved.

Cached playback retains the original generation's validated usage and request/trace identifiers, with `cache_hit: true` and `request_sent: false`; it does not represent new billed usage. Older cache entries without usage metadata remain unknown and are not regenerated. Only plain decimal header values with at most 12 whole digits and six fractional digits are recorded; scientific notation, negative/non-finite values, oversized fields, and invalid identifiers are discarded without echoing them.

## Solana devnet

Install the optional `solders==0.29.0` dependency in the project environment. The adapter uses the SDK to construct and sign a v0 transaction, then Solana JSON-RPC to submit and inspect it. [Solders transaction guide](https://kevinheavey.github.io/solders/tutorials/transactions.html).

`create_report_receipt(report, finalized=True)` returns a mock descriptor. Reports must be JSON objects containing an explicit `simulated` boolean. The digest covers Relay canonical JSON v1: sorted keys, compact UTF-8, finite numbers. This encoding is documented separately from RFC 8785; retain the same report values for verification. Only the digest is written in the memo, not report text, readings, or images.

Live operations require `live=True` and `RELAY_ALLOW_SOLANA_DEVNET=1`. The RPC URL is fixed to `https://api.devnet.solana.com`; mainnet and arbitrary RPC addresses are unsupported. `prepare_devnet_wallet(live=True)` creates or reuses only `.state/solana/devnet-keypair.json` and returns its public address. The new key file is restricted to the current user before secret bytes are written. It does not import other wallets, obtain tokens, or send a transaction. Use only devnet test tokens; the adapter never requests an airdrop.

The receipt call estimates the fee, checks the dedicated wallet's balance, signs one memo instruction, writes the signature locally before sending, submits once with preflight enabled, then checks confirmation once. Repeating the same report checks the saved signature instead of sending another transaction. If confirmation is pending, call `verify_report_receipt(report, receipt, live=True)` later. An unknown submission is not a failed transaction and must not trigger automatic resubmission.

Verification inspects the confirmed transaction's signature, signer, memo program, exact digest bytes, and execution status. A changed report fails the hash comparison without a network call. Local verification of a live receipt returns `valid: null` until its chain evidence is checked. A verified hash proves report integrity, not sensor accuracy. [Memo program](https://www.solana-program.com/docs/memo), [sendTransaction](https://solana.com/docs/rpc/http/sendtransaction), [getTransaction](https://solana.com/docs/rpc/http/gettransaction).

## Proof recipe

1. Run `.venv\Scripts\python.exe -m pytest tests/test_audio_receipt.py -q`. Tests inject fake HTTP/RPC responses; SDK signing is local.
2. Use a reviewed synthetic incident with `simulated: true`. After shared-budget admission, make one live speech request. Save its result and play the generated MP3; repeat the identical request and verify `cache_hit: true` with no new dispatch.
3. Explicitly prepare the dedicated devnet wallet. Arrange a bounded devnet-only funding attempt through the root workflow if needed; stop if the faucet is limited.
4. Finalize the report and create one live receipt. Save its devnet explorer URL and confirmed verification result; if pending, perform a later read-only verification.
5. Change a copy of the report and demonstrate `valid: false`. Keep original and modified results labeled as synthetic input throughout.

No live speech generation, wallet funding, or blockchain submission is implied merely by these adapters or tests existing. The root pipeline owns live credentials, spending reservations, execution evidence, and the current integration status.
