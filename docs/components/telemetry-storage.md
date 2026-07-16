# Telemetry storage

## Why SQLite is used

CSV is useful for the current bounded captures but cannot efficiently support continuous retention, migration, session comparison, anomaly notes, or deletion. SQLite provides a local transactional store without introducing a service or cloud dependency.

## Current records

- `schema_migrations`: applied migration numbers and timestamps.
- `sessions`: mode, trial label, lifecycle state, start/end times, profile fingerprint, notes, and cleanup outcome.
- `events`: ordered full-rate accelerator, axis, wheel, button, relative-motion, special-report, and marker records.
- `aggregates`: one-second summaries for continuous observation.
- `anomalies`: deterministic analyzer markers plus user notes.
- `exports`: export time and format without treating export as automatic deletion.

## Retention

Continuous aggregates and their unmarked discrete events expire after 30 days.
High-fidelity sessions remain until explicit deletion. Export is an auditable,
non-destructive operation. Retention is
transactional and tested at migration boundaries. The current store enables WAL,
foreign keys, a busy timeout, numbered migrations, strict per-session sequence
uniqueness, and marker-centered context queries. A bounded single-writer queue
prioritizes discrete events, counts replaceable aggregate drops under pressure,
and surfaces database failures. Symptom markers bypass that queue and commit
synchronously.
