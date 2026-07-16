# ADR 0002: Separate raw sensor truth from normal scroll truth

- Status: Accepted
- Date: 2026-07-15

## Context

Raw calibration-report mode exposes the paddle's analog value, while normal mode exposes the device's mapped Windows behavior. Hardware evidence shows raw mode may suppress ordinary scroll output. Windows also cannot reliably identify whether a scroll event came from the paddle or physical wheel on the same mouse.

## Decision

Collect raw paddle and normal Windows behavior as separate controlled trials. Require explicit labels and guided physical-control isolation (`paddle_only` or `wheel_only`) rather than inferring the source of a wheel event.

## Why

Combining unlike modes would create false correlations and could hide the boundary at which the fault occurs. Controlled labels preserve causal meaning even when Windows cannot attribute identical scroll events to a physical control.

## Consequences

- Cross-session comparison uses trial phases and repeatable motions, not an assumed shared raw/scroll stream.
- Raw wheel trials are rejected.
- Symptom reports state which observation mode produced the evidence.
- Pointer coordinates are excluded because they do not identify the scroll source or represent cursor movement.
