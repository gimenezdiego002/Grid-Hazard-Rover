# FieldSight AI calling system

This subsystem accepts completed ElevenLabs Agent calls and gives an affiliated
company a protected review queue. Caller statements remain **untrusted call
reports**. They never become canonical hazards or affect the Coordination Risk
Index without a separate reviewed ingestion workflow.

## Live service setup

1. Buy a Twilio number that supports inbound voice.
2. Create an ElevenLabs Agent and import the Twilio number using ElevenLabs'
   native Twilio integration.
3. Start every call with a clear AI and recording disclosure. Ask whether the
   caller consents before collecting or retaining the conversation.
4. Configure the agent's analysis to collect `category`, `sentiment`,
   `urgency`, `location`, and `action_items`.
5. Add dynamic variables `company_id`, `company_name`, and
   `consent_to_record` when routing a call.
6. Configure a `post_call_transcription` webhook to
   `https://<backend>/webhooks/elevenlabs/post-call`.
7. Optionally configure `post_call_audio` to
   `https://<backend>/webhooks/elevenlabs/post-call-audio` only after choosing
   a lawful retention policy.
8. Put the generated webhook signing secret and a separately generated company
   dashboard token in backend environment variables. Never put either in a
   `VITE_*` variable.

Required production configuration:

```text
ELEVENLABS_AGENT_ID=<agent id>
ELEVENLABS_WEBHOOK_SECRET=<webhook HMAC secret>
CALLS_DASHBOARD_TOKEN=<long random value>
```

Local audio saving is disabled by default. Enabling
`ELEVENLABS_SAVE_CALL_AUDIO=true` writes bounded MP3 files under `.state`,
which is ignored by Git and suitable only for a local demo. DigitalOcean's app
filesystem is ephemeral; use private durable object storage with encryption,
access controls, deletion rules, and audit logging before retaining production
recordings.

## Safety and privacy

- The caller must hear that the agent is AI and the call may be recorded before
  the conversation begins.
- Confirm applicable recording, privacy, accessibility, emergency, and
  outbound-calling requirements with counsel. This implementation is not a
  substitute for legal review.
- The agent should direct immediate threats to emergency services and must not
  represent itself as an emergency dispatcher.
- Do not collect CEII, payment credentials, government identifiers, health
  details, or other unnecessary sensitive data.
- Transcript endpoints require a bearer token. List responses omit full
  transcripts; detail and audio endpoints remain protected.
- Webhook bodies are size-limited, HMAC-verified, timestamp-checked, and
  deduplicated by `conversation_id`.

## Local verification

```powershell
.\.venv\Scripts\python.exe -m unittest backend.test_calls -v
```

The tests use signed fixtures and make no Twilio, ElevenLabs, model, or paid
API calls.

