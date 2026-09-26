# MLH prize fit and submission evidence

Checked against the [official ShellHacks MLH prize list](https://www.mlh.com/events/shellhacks-b9/prizes) on September 26, 2026. All **eight** listed categories have a product role. Six have an offline adapter rehearsal, one has live provider smoke evidence (Gemini), and none of this establishes an all-eight live demonstration or award eligibility. The current provider status remains in [the integration matrix](mlh-integrations.md).

GCP stays our primary cloud and Gemini stays our model provider. GCP hosting is already verified, but it does not substitute for the DigitalOcean category. Relay remains separate from the team's utility matching, photo ingestion, shared schemas and risk dashboard; no bridge to those systems is claimed here. This checklist covers the linked MLH list, not every organizer or other sponsor award at ShellHacks.

## One incident, eight useful contributions

The intended connected story is: a station/scout sends an observation through **DigitalOcean**; **Tiger Data** retains its sensor window; **Snowflake** supplies relevant inspection references; **Gemini** interprets the selected evidence on the GCP-hosted application; **MongoDB Atlas** preserves the report and review; **ElevenLabs** speaks one reviewed briefing; **Solana** anchors the finalized report digest. A **GoDaddy Registry** domain gives judges a public project/evidence entry point.

That is the target story, not a description of a working live chain. The current six-stage replay demonstrates its report-processing relationships only with mocks. The separate fleet gateway/consumer is locally tested, and the domain is not registered. Reference retrieval, voice and receipt generation happen for selected incidents, not on every sensor sample. None of these integrations authorizes physical movement or declares a hazard safe.

| MLH category technology | Judge demonstration and evidence needed | Existing implementation / handoff |
|---|---|---|
| **Gemini API** | Show selected readings and reference IDs becoming a structured suspected-hazard finding, with actual model identifier and metered usage. Distinguish the existing real text-only smoke from mock dashboard results; camera interpretation is unproven. | [Model gateway](../src/relay_gateway/providers.py), [reference handoff](data-integrations.md), existing project-key smoke summarized in [cloud evidence](cloud-setup.md). |
| **ElevenLabs** | Play real generated audio and show the exact reviewed script linked to its report. Retain the generation metadata and audio digest. A briefing descriptor or a speaker icon is insufficient. | [Reviewed speech CLI](speech-cli.md); prepared synthetic script in [elevenlabs-briefing.txt](../artifacts/elevenlabs-briefing.txt). Account key and voice remain absent. |
| **Solana** | Open one confirmed devnet transaction, verify its signed memo against the final report, and show that a changed report fails verification. Preserve the simulation label. | [Receipt CLI](receipt-cli.md), [offline tamper proof](../artifacts/receipt-cli-verification.json). Wallet funding is still missing; a local hash is not a transaction. |
| **Tiger Data** | Retrieve the incident's timestamped sensor window from an actual Tiger Data service. Replay the same input with zero new rows and compare all returned event IDs/payloads. | [Telemetry adapter and proof CLI](data-integrations.md), [SQL schema](../deploy/sql/tiger-telemetry.sql). An ordinary local PostgreSQL database would not establish Tiger Data usage. |
| **DigitalOcean** | Show the gateway running on DigitalOcean, authenticated finite event intake and authenticated consumer read-back. Demonstrate duplicates or a disclosed gap without claiming durable gateway storage. | [Deployment recipe](../deploy/digitalocean.md), [finite consumer](fleet-consumer.md). The gateway is a bounded memory/TTL cache; Tiger Data is the intended durable sensor history. Account/deployment remain absent. |
| **Snowflake API** | Capture a real SQL API result/statement handle, preserve its source IDs and passages, then show a metered Gemini finding citing those references. A query result without subsequent model use does not prove our intended retrieval-augmented analysis. | [SQL API adapter and guarded commands](data-integrations.md), [reference schema](../deploy/sql/snowflake-references.sql). Current data is synthetic inspection guidance, not completed-incident history. |
| **MongoDB Atlas** | Save the mission's report and review state, close/recreate the client, and retrieve the same report revision and digest from Atlas. | [Mission store and proof CLI](data-integrations.md). The current proof CLI exercises an isolated synthetic snapshot; linking the actual connected incident is still required. A local MongoDB process would not establish Atlas usage. |
| **GoDaddy Registry domain** | Show eligible registration/ownership and open the chosen project's HTTPS address. Registration is the published category requirement; a useful public page and HTTPS are our demo acceptance checks. | Obtain the legitimate event offer/code, verify the eligible name/extension and final terms, then register and configure the project page. No registration or public domain page exists yet. |

## Connect the evidence before calling it end to end

Separate successful vendor checks are useful connection evidence. To demonstrate the intended joined mission, preserve these identities in one reviewed evidence bundle:

- One mission ID and the original event IDs/UTC observation window through intake and telemetry read-back.
- The returned Snowflake source IDs and exact bounded passages supplied to Gemini, plus its finding and usage record.
- One final report revision, its Atlas read-back digest, review status and explicit `simulated` value.
- The spoken script/audio digest derived from that reviewed report, and the Solana receipt for the exact finalized report bytes.
- The actual DigitalOcean resource/endpoint and the registered HTTPS project address, with credentials and private account details omitted.

The current separate live proof commands do not assemble this bundle automatically. Do not relabel their unrelated synthetic mission IDs as one live mission. A real provider processing synthetic data remains a synthetic-data demonstration; simulated review remains distinct from human approval. Do not modify a finalized report after anchoring its digest.

## Snowflake category interpretation

The event describes API-based AI/RAG applications. Its linked [Snowflake example](https://github.com/Snowflake-Labs/cortex-rest-api-demo) uses Cortex inference, while the [documented SQL API](https://docs.snowflake.com/en/developer-guide/sql-api/intro) supports our existing retrieval implementation. The [MLH Snowflake partner page](https://www.mlh.com/partners/snowflake) also discusses general API and SQL-oriented applications.

Our assessment is that Snowflake SQL retrieval feeding Gemini is a credible fit for the published API/RAG theme. The event page does not explicitly require Cortex inference or Cortex Search, but it does not confirm acceptance of our specific design either. Keep sponsor eligibility **unconfirmed** until clarified with event staff. A useful question to take to the coach is: “Does Snowflake SQL API retrieval supplying source-cited context to Gemini satisfy this event's Snowflake API challenge?” No message has been sent on the team's behalf. There is no reason to replace Gemini or provision an extra model service merely to match an example.

## Domain eligibility and the public page

The event's offer link currently leads to [tech.study](https://www.tech.study/), which features `.US`; this is not evidence that every extension or premium name is covered. Verify the choices presented by the actual redemption flow. The [registry scholarship terms](https://www.about.us/scholarship-terms) describe an attendee's organizer-issued, single-use code, event-period redemption and a 12-month registration; renewal is separate at the registrar's then-current price. Active code validity and the final checkout terms are still unknown.

If selecting `.US`, check the registry's [nexus requirements](https://www.about.us/documents/policies/usTLD_Nexus_Requirements_Policy.pdf) and [registration privacy rules](https://www.about.us/policies/us-privacy-services-policy). Hackathon attendance alone does not establish eligibility. Do not assume `.com`, `.co`, `.biz`, `.tech` or a premium name is included. An available-looking name or DNS lookup is not registration/ownership proof.

The current Cloud Run service intentionally requires authentication and returns 403 to unauthenticated visitors. Pointing a domain at it alone would not produce a usable public judge page. The proposed domain destination is a small public project/evidence page on GCP, with clearly labeled simulation evidence and repository links; authenticated mission controls remain separate. That page and its HTTPS/domain configuration are still pending. Do not silently expose the private API to complete the domain checklist.

## Account handoffs and finishing order

The offline software can be rehearsed now. The remaining live steps need these specific inputs, stored locally or in a runtime secret store rather than chat or Git:

1. **ElevenLabs:** account key, selected voice, model and verified pricing. Generate the existing short reviewed script once, retain the result, then play it.
2. **Atlas, Tiger Data and Snowflake:** selected project-only services, limited runtime credentials, permitted network, schemas and verified resource pricing/lifetimes. Run the existing guarded proof commands individually; then connect the same incident and its source-cited Gemini result.
3. **DigitalOcean:** account access/credits status and a reviewed small gateway deployment under a bounded reservation. Capture intake and consumer read-back from that actual endpoint.
4. **Solana:** verified devnet test-token funding for the dedicated wallet. Submit the finalized report once and explicitly verify confirmation; never buy mainnet tokens or automatically repeat the failed faucet request.
5. **GoDaddy Registry:** the attendee offer/code and an eligible available domain choice. Finish registration, public page, DNS and HTTPS, then check the exact event submission categories before submitting.

Use the existing canonical ledger and [budget policy](budget-policy.md): $20 cumulative authorization, $15 planned, $5 held. Current reservations carry forward; credentials or a new account never create a fresh allowance. Provider trials/credits are not assumed active. Account compute/storage and setup costs need their own bounded reservations in addition to per-operation checks.

**Done when:** each of the eight category rows has the demonstrated provider/domain evidence above, its event-specific eligibility has been checked, and the submission accurately distinguishes real provider use, synthetic data and unconnected hardware. Until then, describe the project as designed for all eight categories with the live proofs still in progress.
