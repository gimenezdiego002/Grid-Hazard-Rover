# Jev comparison results

Reproduced September 26, 2026 from `python -m relay_gateway.jev_cli compare`.

**Fixture replay only. No actual model-quality, hardware, energy or carbon measurement.**

| Strategy | Gemini attempts | Jev attempts | Total attempts | Known tokens | Known estimated USD | Missed hazard frames | Unsafe proposals rejected | Unsafe actions accepted |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| rules | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 |
| gemini | 29 | 0 | 29 | 2201 | 0.004808 | 2 | 0 | 0 |
| hybrid | 23 | 8 | 31 | 2914 | 0.003390250 | 2 | 2 | 0 |

## Fault-free provider subset

The eight missions without injected provider faults have complete illustrative fixture accounting. Observation-quality faults and the deliberate blind spot remain in this subset.

| Strategy | Gemini attempts | Jev attempts | Total attempts | Simulated tokens | Illustrative USD |
|---|---:|---:|---:|---:|---:|
| rules | 0 | 0 | 0 | 0 | 0 |
| gemini | 21 | 0 | 21 | 1696 | 0.003631 |
| hybrid | 18 | 5 | 23 | 2290 | 0.002814104 |

Here the hybrid arm has three fewer Gemini attempts, two more total attempts and 594 more simulated tokens. It has no demonstrated detection improvement. The illustrative dollar estimate reflects two different fixture price schedules, not real comparative billing.

Each arm processes the same 12 missions. All arms retain 10 missions for review. The two model arms each include one injected network failure with unknown token/cost usage, so complete totals are null. Known totals exclude that unknown usage. All fixture paid costs are zero. Counts are logical provider invocations/attempts, not guaranteed billed inference. Invalid-choice rejection counts only proposals reaching the local action gate; Gemini schema rejection is separately recorded in its result.

The hybrid arm uses six fewer Gemini attempts but two more total attempts and 713 more known simulated tokens. Its lower known illustrative dollar estimate does not establish lower actual spend. Both model arms share event-driven admission; no polling baseline is used.

All three arms miss two labeled hazard frames: an unsupported sensor and a deliberately below-threshold reading. Human review is not counted as detection. Local threshold alarms take zero simulated seconds; provider performance has not been benchmarked. The injected six-second deadline case is not measured provider latency.

Fixture SHA-256: `893e017b5e410ddeaa913ecf822d7124c38166a3dc041712301f15f376b14625`.

Versions: `google-genai==2.25.0`, `pollard==1.6.0`, `pollard-jev==0.1`.

Full evidence: [comparison JSON](jev-comparison.json). Demo instructions: [runbook](../docs/jev-demo.md).

Live-attempt records are separate from this comparison. See the runbook and verification artifact for current success/blocker and retained-spending evidence.
