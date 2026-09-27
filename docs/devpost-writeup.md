# FieldSight: budget-aware robot inspection

## Elevator pitch

FieldSight coordinates robot inspections around new evidence. Our interactive prototype combines a rover, a hexapod and an arm with explicit review steps, selective AI analysis, and visible spending limits.

## Inspiration

Physical AI has two costs: moving a robot through the world and deciding when its observations deserve more analysis. Repeatedly asking a model about an unchanged scene adds work without necessarily adding useful evidence. We wanted an inspection system that could explain what changed, why it escalated, and what it spent.

We also wanted to make progress while assembling and connecting different robots. A repeatable simulator let us develop mission logic, rehearse failures, and test the handoffs between a patrol rover, an inspection hexapod, and a station arm.

## What it does

FieldSight supports preset patrols and directed inspections. In our interactive simulation, a rover travels around obstacles, encounters a suspected wet area, and hands off a closer inspection to a hexapod. The mission pauses for review before continuing. A separate virtual arm can perform a marker pick-and-place sequence, record virtual poses, and replay a taught routine.

The demo also makes failure visible. Sensor dropout, low battery, blocked movement, grip loss, and exhausted inference allowance stop or hold the relevant workflow. Clearing a fault requires an explicit recovery action. Acknowledging a suspected hazard does not replenish a spent model allowance or establish that a physical site is safe.

Alongside the simulator, we built an offline incident replay connecting reference retrieval, structured findings, sensor-history storage, mission persistence, a speech descriptor, and report-hash verification. We separately demonstrated real Gemini, ElevenLabs, MongoDB Atlas, and Snowflake API calls using synthetic inputs, plus real database-side SQL in Tiger Data. These component proofs have not yet been joined into one live incident pipeline.

## How we built it

The application uses Python, FastAPI, Pydantic, and a browser interface written in HTML, CSS, and JavaScript. Canvas-based views show the robots and virtual arm. The spatial simulator uses a local metric floor plan and A* navigation; it is a 2D kinematic model rather than a validated physics or terrain simulator.

Deterministic code owns mission state, permitted actions, retries, and budget checks. AI adapters interpret selected evidence or propose constrained decisions. Observations, reports, and simulation exports retain their provenance so a simulated completion cannot be mistaken for a physical confirmation.

We separated timestamped telemetry, mutable mission documents, and inspection reference material into distinct storage roles. That gives each database a specific responsibility instead of copying the same information into every service.

## Challenge categories and technologies

### Gemini API — structured inspection findings

We built a Gemini adapter that turns selected sensor metadata into validated, structured suspected-hazard findings. We completed two real text-only API smoke tests using synthetic readings and recorded the model response and provider usage. The gateway supports bounded reference context and explicit request, token, and estimated-cost limits.

Our current live proof covers text metadata. Camera analysis, live use of retrieved Snowflake passages, and the newer mission/evidence/report supervisor remain unfinished. The dashboard and simulator use mocked analysis.

### ElevenLabs — spoken inspection briefings

We built an explicit speech-generation path for reviewed briefing text, with caching, duplicate-dispatch protection, and spending admission. One real ElevenLabs request turned our 165-character synthetic inspection script into a 10.26-second MP3 using River and Eleven Flash v2.5. We verified the audio format, digest, and full decoding.

This demonstrates real speech generation. Audible semantic review, deriving the briefing from the connected incident report, and playback through StackChan are the remaining steps.

### MongoDB Atlas — mission persistence

We built an Atlas adapter for the latest mission snapshot, review state, and content digest under a stable mission ID. On an isolated Atlas M0 cluster, we inserted a synthetic mission, updated its simulated review state without inserting another document, then recreated the client and retrieved the same content and SHA-256 digest.

The proof demonstrates remote persistence and consistent read-back. The current dashboard still holds its mission state in process memory, and connecting its complete workflow to Atlas remains next work. The adapter stores the latest snapshot; it is not a report revision-history system.

### Snowflake API — traceable inspection references

We implemented bounded retrieval through Snowflake's SQL API to fetch hazard-specific reference passages with source identifiers. A real authenticated query returned two synthetic inspection-reference passages, and we retained the successful statement handle and exact retrieved context.

FieldSight can carry that context into its analysis path. A successful live Gemini response using those passages remains to be demonstrated. Our implementation uses SQL API retrieval; it does not use Cortex Search or Snowflake-hosted model inference.

### Tiger Data — timestamped sensor history

We built a telemetry adapter and indexed PostgreSQL schema for timestamped robot readings, duplicate protection, and bounded queries around an incident. In Tiger Data's browser SQL editor, we demonstrated one synthetic insertion, zero additional rows on identical replay, and exact retrieval after the transaction committed.

That establishes database-side behavior on a real Tiger Data service. Our local application's TLS connection and runtime access still need resolution. The current schema is an indexed PostgreSQL table; we have not implemented hypertables, continuous aggregates, or measured compression benefits.

### Solana — verifiable report receipts

We implemented a devnet receipt adapter with canonical report hashing, memo-transaction signing, and transaction-verification code. The offline demonstration verifies an original report and rejects a modified copy. The intended use is to make a finalized report's bytes independently checkable after publication.

We created a dedicated devnet wallet, but its funding attempt failed. No report transaction has been submitted or confirmed. Our present result is receipt software and offline verification, with on-chain proof still pending. A report hash demonstrates consistency of bytes, not the truth of a sensor reading.

### DigitalOcean — fleet intake service prepared for deployment

We built a bounded, authenticated fleet telemetry gateway and a finite consumer that checks event identities, hashes, duplicates, and sequence gaps. The consumer stores accepted evidence and its cursor locally so interrupted reads can be recovered. We tested the transport locally and prepared an App Platform deployment specification in an isolated DigitalOcean project.

Deployment and remote event intake/read-back remain incomplete. Our verified cloud deployment is on GCP, so we do not count it as a DigitalOcean deployment. The fleet gateway currently retains events in process memory with a time limit; the intended durable telemetry store is Tiger Data.

### GoDaddy Registry — fieldsight.biz

Our teammate registered **fieldsight.biz** through the GoDaddy Registry offer for the project's public identity. The domain is not yet connected to a hosted site. Our next step is to connect it to a public project and evidence page with HTTPS; the private mission API remains a separate authenticated service.

### Google Cloud — hosted application and evidence storage

We deployed a private Cloud Run service in an isolated GCP project and verified authenticated health checks, mission actions, and the six-stage mock replay. Unauthenticated requests were denied. We also uploaded a synthetic report to private Cloud Storage and retrieved identical bytes.

The setup includes Artifact Registry, service accounts, Secret Manager for the project Gemini key, and storage lifecycle policies. Cloud Run was configured to scale to zero with a maximum of one instance. The deployed service is mock-only, has no live-provider secret attached, and predates the newer local simulator work.

### Pollard — make model work measurable

We integrated Pollard's runtime, request/token meters, durable recordings, and verification into the analysis gateway. Local rules admit model work when evidence changes; request, token, and estimated-dollar limits preserve a review-required result when further analysis is refused. A separate cumulative ledger accounts for reservations across providers.

On the same twelve-reading synthetic fixture, the baseline made 12 mock model calls and the economy policy made 1, with 3,743 versus 312 simulated tokens. That is 91.67% fewer calls for this fixture. It is a reproducible software comparison, not a measurement of production savings, energy use, or general detection accuracy.

The newer spatial preset models 80 baseline requests versus 3 admitted requests by filtering 57 routine and 20 duplicate observations. Its actual model calls are zero; token and dollar estimates use disclosed illustrative assumptions. This is a separate experiment from the twelve-reading fixture.

### OpenJev and ngrok — local supervisory decisions

We connected pollard-jev's typed decision and freshness contracts to a constrained supervisory policy and ran a pinned OpenJev model on an RTX 4090 Laptop GPU. Recorded tests include five local inferences and another request through an authenticated ngrok HTTPS tunnel.

Dry observations supported continued monitoring. Wet and conflicting observations produced abstentions, leaving review required and the local alarm latched. Gemini roles in those runs remained fixtures. These results demonstrate local model execution and handling of uncertainty; they do not establish improved accuracy or lower overall inference cost. The recorded demonstration is separate from the hosted TypeSafe Jev path, which has no successful live proof.

### Robotics and Bluetooth — simulation plus an initial hardware connection

We wrote separate simulated controllers for the Quarky Intellio rover, Freenove FNK0052 hexapod, and Hiwonder LeArm. Their finite workflow covers patrol, hazard reporting, kit pickup, inspection, and kit return, with explicit transfer and clearance acknowledgements. We preserved pinned Freenove vendor source and its attribution separately from our own controller code.

Our browser simulator adds visible obstacle-aware movement, inspection review, and a virtual six-joint arm with pose teaching, replay, joint-stall and grip-loss recovery. Virtual pose exports are rejected by the physical motion-recording parsers.

Our team also completed a physical robot demonstration. The interactive multi-robot inspection described above remains simulated; the physical demonstration does not establish that complete mission through FieldSight.

Using Python and Bleak, our separately recorded hardware integration discovered and connected to the LeArm over Bluetooth LE and received a valid non-motion controller response reporting 7,881 mV. A position query received no reply. Earlier operator feedback reported LeArm movement through its vendor app. FieldSight-controlled motion, measured pose capture, physical replay, camera capture, calibrated sensor readings, and StackChan playback are not yet established by our integration evidence.

## Challenges we ran into

The hardest part was preserving the distinction between an intended integration and an observed result. Database-side SQL did not automatically produce a working application connection. A successful model smoke test did not make every later prompt/schema combination valid. Our newer Gemini supervisor requests failed with HTTP 400, and the Solana faucet did not fund the wallet.

Hardware introduced another boundary: discovering a Bluetooth characteristic and reading a controller response did not establish servo limits, position feedback, or verified playback. The simulator let us keep developing coordination and failure handling while those device-specific questions remained open.

## Accomplishments we're proud of

We built a repeatable inspection demo with two mission modes, visible robot roles, review gates, failure injection, taught virtual-arm replay, and explicit model-work accounting. We also captured separate real-provider evidence for model analysis, speech generation, mission persistence, reference retrieval, cloud hosting/storage, and database-side telemetry operations.

At the September 27 audit, the current checkout passed 931 Python tests, 21 subtests, and 35 JavaScript tests. The original offline rehearsal passed all 29 checks, and fresh spatial and virtual-arm rehearsals completed their normal, refusal, and recovery cases. These checks validate the software behaviors exercised; they do not substitute for field testing.

## What we learned

Fewer model calls are useful only when the system still handles the evidence that matters. We learned to measure admitted and refused work separately, preserve uncertainty after failures, and keep synthetic metrics distinct from provider usage and physical measurements. We also learned that reliable multi-robot coordination needs explicit acknowledgements and recovery states even before real hardware is attached.

## What's next

Our next milestone is one traceable incident across the live providers: timestamped telemetry, retrieved references actually used by Gemini, a reviewed Atlas report, an audible ElevenLabs briefing, and a confirmed Solana devnet receipt. We also need DigitalOcean deployment, an HTTPS site connected to fieldsight.biz, and a recorded end-to-end hardware mission with device versions, control methods, and physical results.

FieldSight currently lives alongside the Grid Hazard Rover foundation. It has not yet been connected to that project's utility coordination, photo ingestion, or geographic risk dashboard.

## Built with

Python, FastAPI, Pydantic, Uvicorn, JavaScript, HTML/CSS, Canvas, SQLite, Gemini API, ElevenLabs, MongoDB Atlas, Snowflake SQL API, Tiger Data/PostgreSQL, Google Cloud Run, Cloud Storage, Artifact Registry, Secret Manager, Pollard, pollard-jev, OpenJev, PyTorch, Transformers, CUDA, ngrok, Bleak, and GoDaddy Registry.

Implemented but awaiting live completion: Solana devnet receipts and DigitalOcean deployment. The registered domain is fieldsight.biz; website connection remains pending. Robot hardware targets are Quarky Intellio, Freenove FNK0052, Hiwonder LeArm, and StackChan, with the demonstrated hardware boundary described above.

The eight MLH category technologies were checked against the [official ShellHacks prize page](https://www.mlh.com/events/shellhacks-b9/prizes) on September 27, 2026. This draft describes our work and its evidence; category listing alone does not establish award eligibility.
