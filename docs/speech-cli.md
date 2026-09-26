# One reviewed spoken briefing

One live generation is now demonstrated in [the sanitized proof](../artifacts/elevenlabs-live-proof.json). The reviewed [165-character synthetic script](../artifacts/elevenlabs-briefing.txt) used the premade River voice with Eleven Flash v2.5 and produced a 165,137-byte, 10.263220-second MP3. Its saved hash, MP3 signature and full `ffmpeg` decoding were verified. The audio was rendered for playback, but audible semantic review and physical-device playback remain unverified. The integrated dashboard replay still creates only a mock descriptor.

The provider reported 83 character-cost units with provider-defined billing semantics. The full $0.05 reservation remains `unknown`; neither these units nor public pricing establish the account's USD invoice. Reuse the existing audio for demonstration, and reconcile that same operation before releasing any reservation.

The one-shot command is offline by default. It reads a UTF-8 text file of at most 200 characters (803 input bytes including an optional BOM), requires explicit operator review, and creates no audio, ledger, or network request in mock mode. Mock mode does not read environment credentials.

```powershell
.venv\Scripts\python.exe -m relay_gateway.integrations.speech_cli --text-file artifacts/elevenlabs-briefing.txt --reviewed
```

For a live run, first confirm account access, voice availability, applicable pricing and that the chosen reservation covers the bounded request. Set `ELEVENLABS_API_KEY` through the local environment without pasting it into output. Set `RELAY_ALLOW_ELEVENLABS=1`, `ELEVENLABS_MODEL_ID=eleven_flash_v2_5`, and an explicit verified `ELEVENLABS_VOICE_ID`. The command accepts no key, alternate ledger path, model override, or endpoint on its command line. A configured key alone does not enable a request.

```powershell
# After those checks and local environment configuration:
.venv\Scripts\python.exe -m relay_gateway.integrations.speech_cli --text-file artifacts/elevenlabs-briefing.txt --reviewed --live --max-usd 0.05
```

`--max-usd` is mandatory for live mode, positive, at most $0.25, and limited to six decimal places. It is a reservation chosen from verified pricing, not a computed price or provider billing cap. The canonical `SpendLedger()` retains the existing cumulative $15 planned allowance within $20 authorized; this command never starts a separate allowance. Admission happens at the outbound transport boundary after input, settings, credential format, state paths and cache checks. There is at most one provider request and no retry loop.

The operation ID is `speech:` plus the adapter cache hash of normalized text, voice, model and output format. It does not change with working directory, filename or an arbitrary attempt label. A durable duplicate cannot send again even if its audio cache has been lost. Valid cached audio is returned without initializing the ledger, reserving funds or dispatching; its original usage evidence may still require reconciliation.

Successful live output includes the audio file, digest and provider usage evidence. Its billing remains unresolved: `actual_billed_usd` and `spending.estimated_usd` stay null, and the full reservation is marked unknown until account-specific usage and pricing are reconciled manually against that same operation. A failure to record the unknown status leaves the dispatched reservation held and reports `dispatched_reconciliation_required`. A timeout, malformed response or local recording failure never releases funds automatically.

The underlying adapter records an attempt marker before entering the transport gate. Consequently a budget denial can leave a local attempt marker even though no provider request was sent. The command reports that distinction; it does not delete markers or automatically retry after funds become available. Inspect cache and ledger together before deliberate recovery. See [adapter behavior](audio-receipt.md) and [shared spending contract](integration-contract.md).

Exit code 0 means a mock descriptor or usable live/cached audio was returned; inspect `spending.status` separately for unresolved billing. Exit code 2 means blocked or unresolved generation. Errors are sanitized JSON and omit provider exception text and credentials. This command neither plays audio automatically nor issues robot commands.

Run the focused offline checks with `.venv\Scripts\python.exe -m pytest tests/test_speech_cli.py -q`. They use injected temporary ledgers and fake responses; they do not make provider calls or read the production ledger.
