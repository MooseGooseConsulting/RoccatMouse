# X-Celerator signal chain

## Why this component exists

The visible symptom—unexpected, reversed, repeated, or missing scrolling—can originate at several different layers. Treating every symptom as a calibration problem risks changing the device without fixing the actual cause.

## Layers and evidence

| Layer | Evidence | Fault examples |
|---|---|---|
| Physical paddle and mechanism | repeated endpoint, release, and hands-off trials | binding, weak return, mechanical hysteresis |
| Device-reported paddle value | calibration-mode 0–255 samples, neutral span, endpoints, reversals | reported neutral noise, center drift, clipped range, unstable endpoint |
| Device calibration/profile | stored profile fingerprint and mapping, normal-vs-raw comparison | wrong center/range, wrong paddle function, profile-specific behavior |
| HID and Windows input | MI_03 reports and Raw Input wheel deltas; WinMM axes are recorded but verified insensitive to this paddle | repeated wheel output after owner-declared release, wrong direction, event burst |
| Application | correct Windows events but incorrect application result | application acceleration, event handling, per-app behavior |

## Controlled observation rule

Raw mode observes the device-reported paddle value and normal mode observes mapped behavior. The physical wheel and paddle can produce indistinguishable Windows scroll events, so the user isolates one control per labelled trial. Touch and release are user-declared trial conditions, not inferred device states. The system never uses cursor movement or pointer position to decide which control produced scrolling.

## Diagnosis decision tree

1. If reported raw neutral or endpoints are unstable across repeatable owner-labelled trials, treat mechanical/sensor behavior as a supported hypothesis and do not write calibration.
2. If raw behavior is stable but stored calibration/profile values are inconsistent, allow an evidence-gated device correction plan.
3. If raw behavior and stored mapping are stable but Windows emits incorrect wheel events, evaluate a reversible mapping or host intervention.
4. If Windows events are correct, classify the fault above the device/input layer and preserve the mouse configuration.
