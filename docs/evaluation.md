# Reproducible economy comparison

Use `scenarios/leak.json` for the first comparison. It is entirely synthetic: twelve samples ten seconds apart, one station, and one wet interval. Wetness is an arbitrary normalized integer from 0 to 1000. It is not liters, gas concentration, calibrated sensor voltage, or evidence from a real robot.

Run the same fixture through both modes:

```powershell
.\.venv\Scripts\python.exe -m relay_gateway compare --scenario scenarios/leak.json
```

Use the same mock provider, mission limits, and observation order for both policies. The baseline considers a model call at each ten-second sample. Economy considers a call when wetness crosses the rising threshold of 700; readings at or below 200 reset the gate. The labels define a hazard beginning at 40 seconds and ending before the 80-second sample. Ground-truth labels are for evaluation only and must not enter a model prompt.

The fixture gives both runs up to twelve requests, 24,000 tokens, and a $0.10 illustrative mission allowance. Those are fixture limits, not permission to make live calls. Mock dollar estimates are simulated and actual paid API cost remains zero. A live comparison must use the aggregate budget policy and identify the model/pricing revision.

## Record without exaggeration

| Metric | How to interpret it |
|---|---|
| Accepted/denied model requests | Report both; a denied request is not a successful inference |
| Input/output tokens | Mock usage is synthetic; live usage comes from provider metadata |
| Dollar estimate and actual paid cost | Keep separate; zero paid cost in mock mode is not a claim that cloud inference is free |
| First detection time and missed labeled events | Compare onset against the fixture label; do not use this single easy event as an accuracy benchmark |
| Frames/bytes uploaded | Measure actual transmission when camera/cloud adapters exist; no image transmission is demonstrated by this fixture |
| Robot distance, motor runtime, or watt-hours | Report only after physically measured; none is provided by a stationary software replay |

This fixture tests reproducibility and the call-admission path. It does not validate camera recognition, leak localization, multi-robot navigation, incident clearance, battery life, or robustness to false alarms. Add noisy negative events, gradual leaks, missing readings, reconnects, and ambiguous images before making reliability claims. Test clearance explicitly: no additional cloud call must not be interpreted as proof that an incident is resolved.

## Environmental and frugality pitch

The defensible claim is: **Relay directs compute and robot work toward new evidence and makes the spending visible.** Show the measured difference between policies with the same input and report any detection-delay tradeoff.

Fewer requests, tokens, or bytes indicate reduced work for this workload; they are not direct measurements of cloud energy or carbon emissions. Report watt-hours only with appropriate instrumentation. Estimate water saved only when a measured flow rate and a defensible change in response time support it, and label the calculation as an estimate. There are no measured savings in this repository merely because this plan exists.
