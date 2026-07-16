# X-Celerator signal chain

## Why this component exists

The visible symptom—unexpected, reversed, repeated, or missing scrolling—can originate at several different layers. Treating every symptom as a calibration problem risks changing the device without fixing the actual cause.

## Layers and evidence

| Layer | Evidence | Fault examples |
|---|---|---|
| Physical paddle and mechanism | repeated endpoint, release, and hands-off trials | binding, weak return, mechanical hysteresis |
| Analog sensor | raw 0–255 samples, neutral span, endpoints, reversals | neutral noise, center drift, clipped range, unstable endpoint |
| Device calibration/profile | stored profile fingerprint and mapping, normal-vs-raw comparison | wrong center/range, wrong paddle function, profile-specific behavior |
| HID and Windows input | MI_03 reports, WinMM axes, Raw Input wheel deltas | repeated wheel output after release, wrong direction, event burst |
| Application | correct Windows events but incorrect application result | application acceleration, event handling, per-app behavior |

## Controlled observation rule

Raw mode observes sensor truth and normal mode observes mapped behavior. The physical wheel and paddle can produce indistinguishable Windows scroll events, so the user isolates one control per labelled trial. The system never uses cursor movement or pointer position to decide which control produced scrolling.

## Diagnosis decision tree

1. If raw neutral or endpoints are unstable across repeatable trials, classify the evidence as mechanical/sensor and do not write calibration.
2. If raw behavior is stable but stored calibration/profile values are inconsistent, allow an evidence-gated device correction plan.
3. If raw behavior and stored mapping are stable but Windows emits incorrect wheel events, evaluate a reversible mapping or host intervention.
4. If Windows events are correct, classify the fault above the device/input layer and preserve the mouse configuration.
