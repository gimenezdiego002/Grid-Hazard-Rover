# FieldSight: spend intelligence where evidence changes

## Forty-five-second pitch

“Physical AI has two budgets: the work a robot does and the inference that
coordinates it. FieldSight makes both visible. A rover patrols a site, local rules
notice a change, and a crawler takes a closer look. We send new evidence for
analysis instead of repeatedly asking a model about the same scene. The operator
can follow the route, the evidence, the request allowance and the handoff to an
arm in one workflow.

“Our mobile robots are simulated today. The operator reports that the LeArm works through its vendor app;
we also have a virtual arm that can record and replay poses if the hardware is
unavailable. Connecting a verified physical routine to FieldSight is the next hardware step. This demo
lets us test coordination while that connection is being built. We compare the
same synthetic observations under two inference policies and show exactly what
each would spend.”

## What to emphasize while operating the demo

| Visible behavior | Economic point | Evidence to show |
| --- | --- | --- |
| Local navigation around obstacles | Routine navigation need not spend an LLM request on every movement | Route, distance and elapsed simulation time |
| Rover observation followed by crawler inspection | Different robots have different jobs; escalation happens at a useful decision point | Mission events and each robot's active task |
| Sensor gating and evidence deduplication | Repeated unchanged readings need not repeat inference | Identical observation stream, baseline requests versus admitted economy requests |
| Request allowance refusal | Budget exhaustion leaves uncertainty visible | Review-required state, refusal count and retained suspected hazard |
| Arm handoff preview | A structured plan can become a bounded, repeatable taught routine | Exported proposal and its connection status |
| Virtual arm teaching and replay | Rehearse a repeatable routine when mechanical hardware is unavailable | Animated poses, saved virtual sequence and explicit fault recovery |

The simulator's request, token and dollar comparison is modeled work at explicit
sample rates. It makes no paid provider requests. Simulation distance, battery
and elapsed time describe the model, not physical measurements. Do not convert
those values into a claimed carbon, electricity, battery-life, water or dollar
saving in the real world.

The existing mission lab also offers a separate twelve-reading fixture replay:
its recorded fixed-interval/economy comparison is 12 versus 1 model requests and
3,743 versus 312 simulated tokens. Keep that fixture result separate from the
spatial simulator's counters. Neither experiment is a field accuracy benchmark.

## What the OpenJev evidence adds

The separate [local OpenJev trial](jev-openjev.md) used actual model inference
through `pollard-jev` on synthetic observations. Its dry sequence made one
inference for three frames and reused local state for the two unchanged frames.
Four recorded mission decisions took 454–718 ms; a warm-up and a separate tunnel
smoke check bring the evidenced local attempts to six. Wet and conflicting
observations caused model abstentions while the local supervisor kept its alarm
latched. Gemini roles were fixtures, and no robot was actuated. This trial is
recorded proof, not an active model connection in the browser simulator.

Do not present that narrow reuse result as proof that the entire hybrid workflow
is cheaper or more accurate. The separate [fixture comparison](../artifacts/jev-results.md)
has an eight-mission subset with 21 Gemini attempts and 1,696 simulated tokens
versus 18 Gemini plus five Jev attempts and 2,290 simulated tokens. The hybrid
arm has fewer Gemini attempts but more total attempts and tokens, with no
demonstrated detection improvement. Its dollar estimates use illustrative
fixture prices. The local trial made no hosted-model API calls; local
electricity and hardware costs were not measured.

## The architectural explanation

Local code handles deterministic motion planning, state transitions and budget
checks. Gemini's intended job is interpreting selected ambiguous or visual
evidence. The browser simulator uses synthetic evidence and mocked analysis.
The separate OpenJev supervisor uses `pollard-jev` for typed permitted choices
and freshness/deadline admission, with deterministic local alarms and budget
checks retaining authority. A proposed response remains distinct from a physical
action: a simulator acknowledgment is
never an arm's real completion signal.

The cost of developing robotics also matters: a repeatable simulator allows
mission logic and failure handling to be rehearsed when the mobile hardware is
unavailable. That is a demonstrated development capability here; a quantified
reduction in engineering hours or hardware costs has not been measured.

FieldSight stays separate from the team's Grid Hazard Rover utility-coordination
models and geographic risk calculation. The local floor plan is in meters,
not a utility map or a connection to `/ingest/photo`.

## A useful next measurement

For a future hardware trial, capture the same incident stream for both policies
and report requests, provider-reported tokens, latency, detected/missed labeled
incidents and operator interventions. Record measured robot distance and energy
only when their sensors and instrumentation are available. A cheaper run is
useful only if the inspection still finds what matters.
