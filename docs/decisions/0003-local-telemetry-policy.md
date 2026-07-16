# ADR 0003: Keep telemetry local and tiered

- Status: Accepted
- Date: 2026-07-15

## Context

Continuous observation is useful for intermittent paddle drift, but full-rate indefinite logging would create unnecessary CPU, storage, and privacy costs. Explicit diagnostic sessions need more detail and longer retention than passive observation.

## Decision

Use two local logging tiers: one-second aggregates plus discrete events for continuous observation, and full-rate samples for explicitly started high-fidelity sessions. Retain continuous data for 30 days and marked high-fidelity sessions until export or deletion.

## Why

The tiers preserve enough history to find intermittent faults without treating every moment as a permanent raw capture. Local storage keeps the product independent of an account or cloud service.

## Consequences

- `%APPDATA%\RoccatMouse\config.json` owns runtime configuration.
- `%LOCALAPPDATA%\RoccatMouse\telemetry.sqlite3` owns telemetry.
- SQLite uses WAL and numbered migrations.
- Export is explicit; no background upload exists.
- Automatic startup is not enabled in the initial tray milestone.
