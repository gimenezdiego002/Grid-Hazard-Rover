# Grid Hazard Rover + FieldSight: infrastructure coordination and economical physical AI

## Elevator pitch

Grid Hazard Rover helps infrastructure teams see where planned work overlaps and why a corridor deserves attention. FieldSight adds a robotics inspection prototype that gathers simulated evidence, coordinates a rover, crawler, and arm, and makes the cost of AI decisions visible. Together, our work explores a practical loop: identify a coordination problem, investigate it, review the evidence, and communicate what should happen next.

## Inspiration

Infrastructure projects rarely happen in isolation. A water utility may replace a pipe along the same corridor where a telecommunications company plans an installation and a road agency schedules construction. Flooding, vegetation, damaged infrastructure, and street obstructions can make that shared space even harder to manage. Each organization may understand its own project while missing the activity around it.

The information needed to coordinate those decisions is scattered across utility plans, public records, maps, photographs, field observations, and community reports. We started Grid Hazard Rover with a simple question: what if teams could recognize upcoming conflicts and inspect the surrounding conditions before sending crews into the field?

That question led to a second one: how should an inspection system decide when it needs more intelligence? A robot can produce many observations of an unchanged scene. Sending all of them to a model adds requests, latency, and potential cost without necessarily improving the decision. We wanted to expose those tradeoffs and use AI at the points where new or ambiguous evidence justified it.

FieldSight became the physical AI side of that work. It explores how a patrol rover, a hexapod crawler, a station arm, and an operator could cooperate in an inspection. When the rover and crawler encountered mechanical problems near the deadline, we expanded the simulator so mission development and failure testing could continue. We also gave the arm its own simulation mode so the software demonstration would remain repeatable if the moving hardware became unavailable.

## What it does

Our project brings together two complementary areas of the team's work: geographic infrastructure coordination and reviewed robotic inspection. The coordination dashboard, inspection services, provider adapters, and hardware experiments have different levels of completion. We have implemented connections between several of them, but have not demonstrated the entire system operating as one live, autonomous field deployment.

### See where infrastructure work needs coordination

The Grid Hazard Rover dashboard presents utility projects, public infrastructure records, observed hazards, relationships between them, and geographic risk cells. Operations and company-focused preview views help users explore the area, inspect supporting records, and understand which nearby activities deserve coordination. The company preview filters a selected utility's records; it does not establish production tenant isolation.

Utility-to-utility relationships are the core signal. The backend compares project geometries and schedules; nearby public activity and hazard observations add context. A roadwork record or a rover observation enriches that comparison rather than substituting for a second utility project.

The current two-utility coordination demonstration uses controlled synthetic projects. We have separately documented public-record ingestion samples, but verified future project data from two real utilities is still a data-completion milestone.

The Coordination Risk Index is deterministic and explainable. The current prototype combines four components into a score capped at 100:

| Component | Maximum contribution | What it represents |
| --- | ---: | --- |
| Utility proximity | 40 | Whether project geometries intersect or fall into defined distance tiers |
| Schedule relationship | 25 | Overlapping schedules or work occurring within the coordination window |
| Nearby observed hazard | 20 | The severity of the strongest related hazard |
| Public infrastructure context | 15 | Nearby public works or infrastructure records |

The response includes component scores, reasons, and references to the contributing records. For example, a checked-in synthetic corridor combines crossing projects, overlapping schedules, a severity-four hazard, and nearby public activity: **40 + 25 + 16 + 15 = 96**, classified as critical by the prototype. That number can be traced to explicit inputs rather than a model-generated judgment.

Absent schedule information remains explicitly unknown. Model confidence is retained with a hazard, but the current risk formula uses hazard severity rather than treating confidence as an additional score component. These are prototype prioritization rules, not a validated prediction of an accident or utility failure. The rendered risk cells are illustrative geographic areas, not measured hazard boundaries.

### Turn observations into reviewable evidence

The team backend includes a photo-ingestion and Gemini visual-classification path that produces structured hazard information, including type, severity, confidence, and explanatory notes. A reviewed integration adapter can also translate a suspected finding from the inspection subsystem into the shared geographic hazard contract.

That conversion requires trusted location, time, severity, review status, and stable evidence identities. A provisional model finding cannot invent its own coordinates or silently become a confirmed hazard. Its provenance and simulation status travel with it.

The company-facing calling prototype adds another evidence source: community reports. It accepts and organizes completed AI-assisted call reports for review. Caller statements remain untrusted reports and do not automatically change the Coordination Risk Index. The implemented queue and webhook handling are separate from proof of an operational public phone service.

### Rehearse a multi-robot inspection

FieldSight's simulator supports preset patrols and directed inspections. A virtual rover navigates around obstacles, encounters synthetic evidence, and hands off a closer inspection to the hexapod crawler. The mission pauses for operator review before continuing. Users can inspect the route and event trail, pause or step through execution, and test blocked paths, low battery, sensor loss, or an exhausted model allowance.

The arm has an independent six-joint simulator. It can execute a marker-transfer preset, accept virtual poses, record them into a taught routine, and replay the sequence. Joint-stall and grip-loss scenarios expose how the controller holds and recovers. These are illustrative kinematics and scripted contact behavior; they do not establish calibrated physical grasping.

Simulation exports use a distinct format that the physical motion-recording parsers reject. This lets us rehearse coordination without accidentally treating virtual joint angles as validated servo commands.

## A representative user journey

Consider two utilities planning work along intersecting corridors near a public road project. A coordinator first examines the geometry, dates, and explanation behind the area's risk score. When schedule information is unavailable, the explanation retains that uncertainty rather than fabricating an overlap.

If an observation suggests standing water or an obstruction, the coordinator can inspect the evidence and request further investigation. In the robotics demo, that investigation becomes a directed mission: the rover approaches the target, the crawler contributes a second observation, and the operator reviews the resulting finding. A proposed arm task remains a separate intervention requiring its own validated execution path.

The intended complete workflow then preserves the reviewed incident, links the relevant telemetry and reference material, generates an understandable briefing, and produces a verifiable report receipt. We have an offline replay of that service sequence and separate live component proofs. Completing and recording the joined live incident is our next integration milestone.

## How we built it

### Shared geographic contracts and explicit integration boundaries

The coordination backend uses Python, FastAPI, Pydantic, and MongoDB. The canonical shared models are `Project`, `Record`, `Hazard`, `Match`, and `RiskCell`. They provide a common geographic contract for the team backend, frontend, data pipeline, and rover upload path.

The inspection subsystem has separate mission, observation, finding, reference, and budget models. We preserved those meanings and implemented an explicit reviewed adapter between the systems instead of treating all records as interchangeable. The team's combined application also mounts the inspection applications under dedicated routes while preserving their standalone entry points.

Geographic storage and API data use GeoJSON in longitude-latitude order. Map rendering converts coordinate order where the mapping library requires it. The matching engine uses a locally centered metric projection and closest points, rather than interpreting degrees as meters or substituting centroid distance for the distance between actual project shapes. Its tiers distinguish crossing projects and separations under 1.6, 8, and 40 kilometers; more distant pairs are excluded.

Timeline matching uses a 180-day coordination window. Completely absent dates remain unknown. Where only one date is supplied, the current implementation treats it as a point date rather than reconstructing an unsupported project duration.

### Public records with traceable normalization

The data pipeline retrieves structured public infrastructure records, validates their geometry and fields, and normalizes accepted records into the shared contract. Existing ArcGIS data can enter that path directly without spending an LLM request to re-extract already structured fields.

Historical ingestion notes record 20 accepted records from a 20-record FDOT Active sample and 14 accepted records from a 20-record Work Program sample, with six rejected. The recorded iMDC Power query returned no records. These samples establish specific retrieval and normalization results; they do not establish complete regional coverage or fulfill the separate requirement for two real utilities' future project schedules.

### A map that explains its results

The geographic frontend uses React, TypeScript, Vite, and Leaflet with OpenStreetMap. Different visual treatments identify projects, public records, hazards, and risk areas. Grouping nearby items and exposing details help users inspect dense areas without losing the supporting evidence behind a marker or score. A separate Google Geocoding helper is implemented; the audited branch does not establish a live Google Routes integration.

The geographic risk layer and the robotics simulation use different coordinate systems for different purposes. The map represents real-world longitude and latitude; the inspection scene is a local floor plan measured in meters. A simulator target is not automatically a geolocated field observation.

### Deterministic control around model output

Local code owns mission state, allowed transitions, evidence freshness, duplicate handling, request limits, and recovery. AI adapters interpret selected evidence or propose constrained supervisory choices. A response is checked before it can affect the workflow, and a failed request leaves uncertainty visible.

Mission commands carry stable action identities so an interrupted response can be recovered without blindly repeating the underlying action. Stale commands are rejected. Budget exhaustion preserves a review-required or holding state rather than clearing a suspected hazard. These controls give the operator a visible explanation of what happened and what can happen next.

### A browser fallback that preserves the real simulation logic

The public FieldSight simulator is deployed on Vercel. Its reviewed Python simulation engines run through Pyodide and WebAssembly in a browser worker, with an independent scene for each tab. The browser interface uses HTML, CSS, JavaScript, and Canvas for the fleet and arm views.

This deployment serves static assets. It makes no model calls, connects to no robot, and exposes no provider credentials. Reloading the page resets that tab's simulation and taught virtual poses. The public AI workflow page separately presents recorded OpenJev results and their evidence identifiers; it does not start a live model service.

The simulator is a 2D navigation and mission-control model, with A* pathfinding and illustrative robot animation. Traction, terrain stability, contact dynamics, and real sensor accuracy require physical testing beyond this prototype.

## Economy and efficiency of AI workflows

We treated AI economy as a measurable engineering question. Routine navigation, threshold checks, duplicate detection, and unchanged observations can often be handled locally. Model work becomes more useful when it addresses a changed condition, ambiguous evidence, or an explicit need for interpretation.

Pollard records model work and applies request, token, and estimated-cost limits in the analysis gateway. A separate durable ledger reserves cumulative dollar spending across providers, including unresolved attempts. Creating a new mission or restarting a process does not create a new spending allowance. Local request accounting and provider billing are recorded as different things.

We kept three experiments separate:

| Experiment | Recorded result | What the result supports |
| --- | --- | --- |
| Twelve-reading analysis fixture | 12 baseline versus 1 economy mock model call; 3,743 versus 312 simulated tokens | The event-driven policy avoided repeated analysis on that controlled fixture: 91.67% fewer mock calls |
| Completed spatial patrol | 80 modeled baseline requests versus 3 admitted requests, after filtering 57 routine and 20 duplicate observations | The simulator demonstrates request admission and makes its assumptions visible; actual model calls are zero |
| Actual local OpenJev dry sequence | Three frames used one inference and two reuses of unchanged local state | A narrow recorded example of avoiding repeated local inference while the state remained eligible for reuse |

The broader comparison also challenged our initial intuition. In an eight-mission fixture subset without injected provider faults, the Gemini-only strategy made 21 attempts and used 1,696 simulated tokens. The hybrid made 18 Gemini attempts plus five Jev attempts, for 23 total attempts and 2,290 simulated tokens. Fewer Gemini calls did not produce fewer total calls or tokens, and improved detection was not demonstrated.

We therefore do not claim measured production savings, lower energy use, or reduced carbon emissions. A useful future comparison must consider total requests, provider usage, latency, missed events, review burden, and billing evidence together.

Physical AI has a similar measurement problem. Robot travel, battery indicators, and elapsed time in our simulator describe the model, not measured hardware efficiency. The demonstrated benefit is a repeatable way to develop and inspect coordination behavior while hardware is unavailable. Quantified engineering-time, hardware-cost, electricity, or environmental savings would require additional measurements.

## Challenge integrations and supporting technologies

We gave each service a specific responsibility in the incident workflow. The eight MLH integration targets are Gemini, ElevenLabs, MongoDB Atlas, Snowflake, Tiger Data, Solana, DigitalOcean, and GoDaddy Registry. Our supporting cloud, simulation, and governance work adds GCP, Vercel, Pollard, OpenJev, and ngrok. Defined roles and implemented adapters do not mean every service has been demonstrated together live.

### Gemini API — structured hazard interpretation

The team implements a visual photo-classification path, while FieldSight's analysis gateway accepts selected sensor metadata and bounded reference context. Both approaches aim to produce structured findings that software can validate and a person can review.

Our separately retained FieldSight live proof consists of two successful text-only API smoke tests on synthetic readings, with validated findings and provider usage. That evidence does not independently establish the visual pipeline or a live analysis using retrieved Snowflake passages. The newer mission/evidence/report supervisor also needs a successful live run; its recorded Gemini attempts did not return usable results.

### ElevenLabs — understandable briefings and call reports

We implemented an explicit speech-generation path for reviewed briefing text, with caching, duplicate-dispatch protection, and spending admission. A real request converted a 165-character synthetic inspection script into a 10.26-second MP3 using River and Eleven Flash v2.5. We verified its format, digest, and decoding.

The calling subsystem adds signed, timestamp-checked, deduplicated webhook intake and a protected review queue for completed conversations. It is a separate contribution from the generated briefing proof. Audible review, automatic linkage to a completed live incident, robot playback, and a fully configured public calling service remain distinct milestones.

### MongoDB Atlas — canonical records and mission persistence

MongoDB supports the coordination platform's geographic records. The separate Atlas mission adapter preserves a latest snapshot, review state, and content digest under a stable mission identity.

On an isolated Atlas M0 cluster, we inserted a synthetic mission, updated its simulated review state without creating another document, and retrieved the same contents and SHA-256 digest through a fresh client. This demonstrates remote persistence and consistent read-back. The FieldSight dashboard still uses process-local mission state, and the public simulator uses tab-local state; neither automatically becomes Atlas-backed because the adapter proof succeeded.

### Snowflake API — traceable inspection references

We implemented bounded SQL API retrieval of hazard-specific reference passages with source identifiers. A real authenticated query returned two synthetic inspection-reference passages, with a retained statement handle and exact context.

The gateway can carry that reference context into analysis. Successful live Gemini use of those retrieved passages is still pending. Our contribution uses Snowflake SQL API retrieval, with source traceability and bounded queries; it does not claim Cortex Search or Snowflake-hosted inference.

### Tiger Data — timestamped telemetry around an incident

We built a telemetry adapter and indexed PostgreSQL schema for robot readings, duplicate protection, and bounded time-window queries. In the real service's browser SQL editor, we demonstrated one synthetic insertion, zero additional rows on identical replay, and exact retrieval after commit.

That establishes database-side behavior. The local application's TLS connection and runtime access still need resolution. Our current schema is an indexed PostgreSQL table; hypertables, continuous aggregates, and compression measurements are future work.

### Solana — verifiable report receipts

The devnet receipt adapter implements canonical report hashing, memo-transaction signing, and transaction verification. The offline demonstration accepts the original report and rejects a modified copy, showing how a recipient could check that a report's bytes have changed.

A dedicated devnet wallet exists, but funding was unsuccessful and no report transaction has been submitted or confirmed. On-chain proof remains pending. Even a confirmed hash would establish consistency with recorded bytes, not independently prove that a sensor observation was true.

### DigitalOcean — a prepared fleet intake service

We implemented a bounded, authenticated fleet telemetry gateway and a finite consumer that checks identities, hashes, duplicates, and sequence gaps. The consumer retains accepted evidence and its cursor so interrupted reads can be recovered.

Local transport tests and an App Platform deployment specification are complete. Remote deployment and event read-back remain pending. The existing verified cloud deployment is on GCP, which we do not count as a DigitalOcean result.

### GoDaddy Registry — a public identity

Our teammate registered **fieldsight.biz** through the GoDaddy Registry offer. The domain is not yet connected to the hosted demo. Connecting it to the public project and evidence pages with HTTPS is the next step; the authenticated mission API remains a separate service.

### Google Cloud — private hosting and evidence storage

We deployed a private Cloud Run service and verified authenticated health checks, mission actions, and the six-stage mock replay. Unauthenticated requests were denied. A synthetic report uploaded to private Cloud Storage was retrieved with identical contents.

The setup includes Artifact Registry, dedicated service accounts, Secret Manager, and storage lifecycle policies. The verified Cloud Run configuration scales to zero and permits at most one instance. That revision is mock-only and predates the newer simulator; the current browser simulator is the separate Vercel deployment.

### OpenJev, pollard-jev, and ngrok — constrained local supervision

We used `pollard-jev` for typed decision and freshness contracts and its OpenJev provider adapter, then ran a pinned local NLI model on an RTX 4090 Laptop GPU. The recorded evidence includes one warm-up, four mission decisions, and one additional request through an authenticated ngrok HTTPS tunnel.

The model proposes only bounded supervisory choices: hold, request evidence, escalate for Gemini interpretation, or continue passive monitoring. Local checks validate the choice, allowed actions, freshness, and deadline after inference. The model cannot supply arbitrary motor commands or clear a latched alarm.

The four mission decisions took 454–718 milliseconds at the provider boundary in this small trial. Dry observations supported monitoring; wet and conflicting observations produced abstentions that preserved the alarm and review requirement. Gemini roles were fixtures in these runs. These are recorded local-model and transport proofs, separate from the public simulator and from the unverified hosted TypeSafe Jev path.

### Robotics and Bluetooth — physical targets with repeatable software fallbacks

Our hardware targets include the Quarky Intellio rover, Freenove FNK0052 hexapod, Hiwonder LeArm, and a planned StackChan announcement role. We wrote project-owned simulated controllers for patrol, reporting, kit transfer, inspection, and return, and retained the Freenove vendor source with its attribution separately.

The team reports a partial physical robot demonstration, and the LeArm was reported moving through its vendor app. Our recorded software integration used Python and Bleak to establish Bluetooth LE discovery and connection and obtain a valid non-motion controller response reporting 7,881 mV. The position query received no reply.

That proof establishes communication, not calibrated FieldSight-controlled motion. Bluetooth-module metadata does not establish the arm controller's exact revision. Reliable position capture, a validated taught routine, physical replay, and an attended end-to-end multi-robot mission remain work to complete. The rover, crawler, and arm simulators provide usable fallbacks in the meantime.

## Challenges we faced

**Keeping geographic meaning consistent.** Longitude-latitude ordering, metric projection, closest-point geometry, and partial schedules all affect whether a coordination result is useful. We treated them as contract rules and exposed uncertainty rather than hiding it behind a convincing map.

**Making dense information readable.** Projects, public records, hazards, and risk areas can occupy the same space. Layer styling, grouping, selection, and expandable evidence details were necessary to help users understand relationships rather than just see more markers.

**Coordinating independent subsystems.** A mission observation, a caller statement, a suspected finding, and a canonical hazard have different meanings. We introduced explicit adapters and review requirements so that data could cross those boundaries without silently acquiring a stronger claim.

**Recovering from interrupted work.** A failed browser response does not always mean an action failed. Stable identities, duplicate protection, read-back, and explicit recovery states helped us avoid replaying uncertain work or losing the evidence that an action already occurred.

**Working through hardware failures.** Mechanical problems prevented a reliable mobile-robot mission near the deadline. Building the simulation fallback let us continue testing mission logic, operator review, and arm routines. It also made the remaining hardware questions more specific: calibration, position feedback, mobility, stopping, and repeatable execution.

**Proving integrations individually.** Real database-side SQL did not automatically establish an application connection. A successful model smoke test did not guarantee that a later prompt and response schema would work. We encountered failed supervisor requests, unresolved telemetry access, and unsuccessful devnet funding, and kept those results separate from completed proofs.

## Accomplishments we are proud of

We developed an infrastructure-coordination backend with explainable spatial and schedule relationships, a geographic dashboard, and a reviewed path for inspection findings to enter the shared hazard model. We also added a company-facing call-report workflow that preserves the distinction between a report and a validated hazard.

We turned a hardware-constrained inspection demo into a repeatable software experience: two mobile robot roles, preset and directed missions, visible evidence and review, failure injection, a virtual arm with taught replay, and model-work accounting. The public browser deployment makes that experience accessible without requiring the visitor to configure Python, a GPU, or robot hardware.

Beyond simulation, we retained separate real-provider results for Gemini analysis, ElevenLabs speech generation, Atlas persistence, Snowflake reference retrieval, GCP hosting/storage, and Tiger Data database operations. We also recorded actual local OpenJev inference and an initial non-motion LeArm Bluetooth response.

At the latest FieldSight publication check, the inspection branch passed **931 Python tests and 21 subtests**, **44 Node tests**, and an additional real Pyodide runtime rehearsal. The runtime completed the fleet mission and virtual-arm preset and exercised refusal, stale-command rejection, repeated actions, teaching, and recovery. These checks describe the inspected software branch, not validation of every teammate branch or real-world robot safety.

## What we learned

Useful infrastructure intelligence must explain its evidence. A score is more valuable when the user can inspect the contributing projects, schedule relationship, hazard, and public record. A finding is more useful when its source, uncertainty, and next review step remain visible.

We learned to assign deterministic responsibilities to deterministic code. Freshness checks, permitted actions, duplicate protection, spending reservations, and local alarm handling remain explicit even when a model proposes an interpretation. An abstention can be a useful result when the controller preserves the evidence and holds for review.

We also learned to evaluate economy across the whole workflow. Moving work from one model to another can reduce a particular provider's calls while increasing total work. Request counts, token estimates, provider usage, latency, and electricity consumption answer different questions and need separate measurements.

Finally, simulation helped us identify operational requirements before the complete hardware workflow was ready. It exposed where a mission should pause, how a failed handoff should recover, and which acknowledgements must come from an actual device rather than a software animation.

## What's next

Our immediate priority is one recorded, traceable incident across the coordination and inspection components: select a mapped location, create a mission, collect timestamped and geolocated evidence, review the finding, pass it through the existing shared-schema adapter, and show the resulting deterministic risk update. The public local-floor simulator will remain clearly labeled during that work.

We then want to connect the independently proven provider components: resolve application telemetry access, persist actual mission state, demonstrate Gemini using retrieved reference passages, generate a briefing directly from reviewed incident facts, and confirm a Solana devnet receipt. DigitalOcean deployment, the custom domain connection, and validation of the calling service are additional concrete milestones.

Hardware work will focus on reliable mobility and capture, confirmed device/controller versions, calibrated arm limits, usable feedback or a verified taught routine, and attended stop/recovery tests. We will claim software-controlled physical replay only after recording that behavior on the real device.

For AI evaluation, we plan repeated comparisons across varied and labeled incidents, reporting total inference work, missed events, latency, review burden, and billing evidence. Physical efficiency claims will require measured distance, energy, sensor reliability, and task completion on hardware.

Our longer-term vision is a shared infrastructure intelligence network: utility plans, public activity, community reports, fixed sensors, and mobile inspection evidence informing a continually updated view of a city. Forecasting failures, coordinating construction schedules, and notifying affected organizations are future goals. The foundation is the same principle we used in the prototype: make the evidence, uncertainty, and cost of a decision visible.

## Built with

**Coordination and interface:** Python, FastAPI, Pydantic, MongoDB, GeoJSON, Shapely, pyproj, React, TypeScript, Vite, Leaflet, OpenStreetMap, HTML, CSS, JavaScript, and Canvas.

**AI and workflow governance:** Gemini API, ElevenLabs, Pollard, pollard-jev, OpenJev, PyTorch, Transformers, CUDA, and SQLite.

**Data, deployment, and transport:** MongoDB Atlas, Snowflake SQL API, Tiger Data/PostgreSQL, Google Cloud Run, Cloud Storage, Artifact Registry, Secret Manager, Vercel, Pyodide, WebAssembly, ngrok, and Bleak. Solana devnet receipts and DigitalOcean deployment are implemented/prepared areas awaiting the live milestones described above. GoDaddy Registry supplies the registered fieldsight.biz domain.

## Demo and source

- [Public FieldSight rover, crawler, and arm simulator](https://shellhacks-relay-robotics.vercel.app/)
- [Recorded OpenJev and AI workflow evidence](https://shellhacks-relay-robotics.vercel.app/workflow-proof.html)
- [Team GitHub repository](https://github.com/gimenezdiego002/Grid-Hazard-Rover)
- [Published FieldSight inspection branch](https://github.com/gimenezdiego002/Grid-Hazard-Rover/tree/relay/inspection-system)
- [Team coordination and integration branch reviewed for this draft](https://github.com/gimenezdiego002/Grid-Hazard-Rover/tree/Diego-Crawler-Plan)

This draft describes the September 27, 2026 prototype. The public simulator, separate live component proofs, implemented integration code, and team-reported physical demonstration are identified separately throughout; none alone establishes a fully live autonomous deployment.
