# Relay's pollard-jev bridge

`src/relay_gateway/jev_pollard.py` is a pure admission gate for Relay supervisory
choices. It uses the actual `pollard-jev==0.1` package's `DecisionRequest`,
`Observation`, `ActionChoice`, `PolicyOutcome` and `fresh()` interfaces. It calls
no provider and dispatches no action. The parent Relay controller retains local
alarm handling, holding, evidence validation and numeric thresholds.

## Reproducible package inspection

On September 26, 2026, the [PyPI release](https://pypi.org/project/pollard-jev/0.1/)
and [upstream source](https://github.com/jemsbhai/pollard-jev) published version
`0.1`. The downloaded `pollard_jev-0.1-py3-none-any.whl` SHA-256 was:

```text
9b2879f369329d38b521b0b2f1a6d93661ae4926cfc8c240446a68f39cad2a3f
```

The released `contracts.py`, `policy.py`, `loop.py` and `providers/base.py`
matched the read-only local project at
`E:/data/code/claudecode/pollard-jev` after newline normalization. No local
changes, publishing, heavyweight model download or inference were performed.
Release metadata requires Python >=3.11, Pollard 1.6.0 and Pydantic >=2.13.5,<3.
The `openjev` extra is unnecessary for Relay's hosted TypeSafe adapter.

## Why Relay extends the policy

The release's `DecisionProvider.infer(tuple[DecisionRequest, ...])` interface is
generic, but its `DecisionPolicy` requires front range, camera clearance,
battery and stuck-state features. Its registered skills are specifically
`continue`, `inspect`, `recover` and `request_help`, with toy motion/measurement
parameters. Those features and meanings are not Relay's observation contract.
The built-in policy cannot be relabeled to authorize Relay actions safely.

Relay therefore uses a separate, named policy,
`relay-supervision-admission-v1`, with exactly these zero-parameter labels:

| Choice | Meaning in this integration |
| --- | --- |
| `hold` | Keep the simulated controller holding for review. |
| `request_evidence` | Request one fresh structured observation while holding. |
| `escalate_gemini` | Request bounded interpretation from Gemini while holding. |
| `continue_monitoring` | Continue passive local monitoring; no motion. |

The model cannot provide distances, gait instructions, servo timing or arbitrary
commands. The controller narrows this allowlist using deterministic facts. In
particular, uncertainty or a latched alarm removes `continue_monitoring`.
Admission is only permission for a simulated supervisory receipt; it is not
proof of task completion, hazard clearance or hardware operation.

## Calling the bridge

```python
from relay_gateway.jev_pollard import validate_choice

admission = validate_choice(
    choice="request_evidence",  # Untrusted provider output, handled as data.
    allowed_actions=("hold", "request_evidence", "escalate_gemini"),
    observed_at_seconds=10,
    now_seconds=11,
    max_age_seconds=5,
    deadline_expired=False,
    request_id="mission-001-observation-001",
)
assert admission.accepted
assert admission.as_dict()["dispatched"] is False
```

`observed_at_seconds` must be the earliest timestamp among all observations
required by the current controller snapshot. It must not be replaced by the
provider-response time or newest observation to conceal older evidence.
`None` is explicitly missing. The application must first detect missing,
conflicting and unsupported observations; this bridge receives only its
resulting temporal context and narrowed actions, not raw sensor readings.

Relative simulation seconds map to a fixed, timezone-aware January 1, 2026 UTC
epoch solely to use the package's temporal contracts reproducibly. The typed
observation is a controller-snapshot presence marker, not a fabricated sensor
reading. It records the snapshot's validity envelope. The package checks
`observed_at <= now < valid_until`; the expiry instant itself is stale.

Recheck the current allowlist, evidence age and deadline immediately before
recording a simulated action receipt. A valid proposal can become invalid while
waiting for a provider. Every rejection has `accepted=False, action=None`.
The local controller must continue holding/alarming independently, including
when `hold` itself cannot be admitted from stale model evidence.

The bridge never invents a score to satisfy the package's `ProviderResult`.
TypeSafe choice confidence and independent support are not interchangeable with
a categorical probability distribution. Scores cannot override controller
invariants or prove a hazard clear.

## Separate accounting and safety responsibilities

The upstream `DecisionLoop` counts logical provider batch attempts and starts a
new allowance for every instance. It does not meter tokens or dollars. Its
timeout discards late results, but cannot terminate arbitrary inference already
running in a worker. It is a simulated single-process supervisor, with no
physical watchdog or guaranteed actuator recovery. Relay does not instantiate
that toy simulator or reuse its per-loop allowance as a spending authority.

The [canonical integration contract](integration-contract.md) remains binding:
explicit live opt-in, one atomic reservation per outbound attempt through
`SpendLedger`, no implicit SDK retry, and retention of unresolved reservations.
Pollard request/token governance and the shared dollar gate are application
layers surrounding actual provider work; this pure bridge does not authorize
network access or spend. Budget refusal must preserve local alarms and holding.

The optional upstream OpenJev adapter targets the independent
`AlexWortega/openjev` NLI implementation. It is not TypeSafe's hosted Jev API and
does not demonstrate Raspberry Pi inference. The separate Relay TypeSafe
adapter operates on structured text/JSON; Gemini remains responsible for
mission interpretation, selected evidence and reports.

## Offline verification

From the repository root, after installing the reviewed dependencies:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_jev_pollard.py
```

The bridge's 43 tests passed on September 26, 2026 against the actual installed
0.1 package. They cover permitted labels, restricted actions during alarms,
unknown commands and parameters, missing/future/stale observations, expiry
between admission checks, deadline expiry, malformed temporal context and
allowlists, and sanitized rejection records. Every test is offline and every
receipt is explicitly simulated. This proves admission behavior, not model
quality, cloud integration, physical operation, energy use or carbon savings.

Done when the controller uses this gate after each provider proposal with the
current temporal context and permitted choices, all rejected proposals leave
local holding/alarms intact, and the offline integration comparison records
those outcomes separately from any actual provider measurements.
