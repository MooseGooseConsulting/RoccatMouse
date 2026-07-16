# Hardware capture evidence — 2026-07-15

## Why this record exists

The purpose of capture is to distinguish a noisy or failing analog paddle from
a stable sensor whose calibrated mapping produces bad scroll behavior. This
record preserves what the local Windows 11 captures actually show. It does not
authorize calibration writes or claim that cursor movement is relevant.

## Evidence

| Capture | Mode and operator intent | Result |
|---|---|---|
| `verification-raw-idle.csv` | raw, untouched | 255 reports; 105–106; one-count neutral span |
| `tyon-xcelerator-raw-20260715-175825.csv` | raw, one-sided movement | 1,077 reports; 106–208; two-second baseline span 1 |
| `tyon-xcelerator-raw-20260715-182945.csv` | raw, both paddle directions | 1,092 reports; 24–210; two-second baseline median 115 and span 1 |
| `paddle-movement-01.csv` | legacy normal paddle trial | 50 scroll events in 8 bursts; 38 negative and 12 positive |
| `tyon-wheel-20260715-192314.csv` | legacy normal physical-wheel trial | 155 scroll events in 13 bursts; 81 negative and 74 positive |

The legacy normal files used `pynput` and predate the version-2 schema. Their
pointer-coordinate columns are ignored: they describe callback location, not
scroll-caused cursor motion. Trial attribution comes from the controlled
one-input-at-a-time procedure.

## Current inference

- The final safety read confirmed active profile 1 maps `thumb_paddle_up` to
  `scroll_up` and `thumb_paddle_down` to `scroll_down`; the physical wheel is
  also mapped normally.
- The raw neutral signal is stable in successful untouched baselines.
- The sensor can traverse a wide range in both directions, approximately
  24–210 in the strongest controlled raw capture.
- The Windows scroll path works reliably for the physical wheel and has worked
  for the paddle.
- Paddle scroll output is markedly asymmetric in the available controlled
  normal trial, while physical-wheel output is balanced.

This evidence makes gross neutral sensor noise and the Windows cursor pipeline
unlikely primary causes. The leading hypotheses are asymmetric device
calibration, profile mapping/threshold behavior, or a mechanical return issue
that appears only during particular actuations. A labelled symptom reproduction
and current-schema Raw Input paddle/wheel pair are still required before choosing
a correction.

## Acceptance status

The current version-2 Raw Input adapter was verified live with Tyon movement and
button packets and with synthetic wheel packets in both directions. Two attempted
current-schema controlled windows received no physical wheel packets, so they
are retained locally as negative runs and do not satisfy hardware acceptance.
The CLI and GUI now fail such controlled trials explicitly instead of reporting
success. A final device read found all five profiles readable and the raw-mode
recovery marker absent.
