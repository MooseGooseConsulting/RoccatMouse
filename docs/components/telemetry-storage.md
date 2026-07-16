# Telemetry storage

## Why SQLite is planned

CSV is useful for the current bounded captures but cannot efficiently support continuous retention, migration, session comparison, anomaly notes, or deletion. SQLite provides a local transactional store without introducing a service or cloud dependency.

## Planned records

- `schema_migrations`: applied migration numbers and timestamps.
- `sessions`: mode, trial label, lifecycle state, start/end times, profile fingerprint, notes, and cleanup outcome.
- `events`: ordered full-rate accelerator, axis, wheel, button, relative-motion, special-report, and marker records.
- `aggregates`: one-second summaries for continuous observation.
- `anomalies`: deterministic analyzer markers plus user notes.
- `exports`: export time and format without treating export as automatic deletion.

## Retention

Continuous aggregates and their unmarked discrete events expire after 30 days. High-fidelity sessions remain until explicit export or deletion. Retention is transactional and tested at migration boundaries. WAL checkpointing and bounded batching prevent capture threads from blocking on every sample.
