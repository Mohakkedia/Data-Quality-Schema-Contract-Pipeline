# Contract Changelog — sensor_readings

## v2 — 2026-09-09
**Breaking change.** Added required field `firmware_version` following the
fleet-wide sensor firmware rollout completed 2026-09-09. Batches produced
by sensors still reporting under the old format (no `firmware_version`
field) fail v2 validation with a `missing_required_field` violation.

The pipeline selects the contract version to validate against based on
each batch's own run date (the version whose `effective_date` is the
latest one on or before that run date) — so batches from before the
rollout are correctly validated against v1, and batches from the rollout
date onward are validated against v2, without needing a manual switch.

## v1 — 2026-01-01
Initial contract. Fields: `line_id`, `timestamp`, `temperature_c`,
`vibration_mm_s`, `throughput_units_min`.
