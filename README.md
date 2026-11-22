# ✅ Data Quality / Schema Contract Pipeline

Validates incoming daily data batches against **versioned schema
contracts** before admitting them into a lakehouse, detects statistical
drift even in batches that technically pass, quarantines (not silently
drops) anything that fails, and alerts — with a Streamlit dashboard
tracking pass/fail/drift trends over time. This is the unglamorous,
"robust architecture for data orchestration" work that's the difference
between a pipeline that ships once and one that survives contact with
real, messy, evolving production data.

## The story this pipeline's own output tells

10 simulated days of `sensor_readings` batches, deliberately varied, run
through the real pipeline:

| Day | What happens | Result |
|---|---|---|
| 1-3 | Clean batches | ✅ PASS |
| 4 | Producer bug: 15% of rows have a null `vibration_mm_s` | ❌ FAIL, 30/200 rows quarantined, **alert sent** |
| 5 | Clean again | ✅ PASS |
| 6 | Sensor recalibration begins: temperature +3°C vs. baseline | ✅ PASS, but drift flagged (moderate, PSI < 0.25 — no alert yet) |
| 7 | Recalibration drifts further: +5.5°C | ✅ PASS, **drift alert sent** (PSI 0.997, "significant") |
| 8 | Bad deploy: `throughput_units_min` sent as text for 10 rows | ❌ FAIL, **alert sent** |
| 9 | Fleet firmware rollout completes; batch now includes `firmware_version` | ✅ PASS against contract **v2** (auto-selected by date — see below) |
| 10 | Clean, v2-shaped | ✅ PASS |

This isn't a cherry-picked success story — `scripts/simulate_batches.py`
generates the messiness on purpose, and every number above comes from
actually running `scripts/run_all_days.py` (see `outputs/quality_trend.jsonl`
and `outputs/alerts.jsonl` for the real, unedited output).

## Contracts are versioned data, not code

`contracts/sensor_readings_v1.yaml` and `..._v2.yaml` are plain YAML — a
data producer or governance reviewer can approve a schema change by
reading a small diff, no Python required. `contracts/CHANGELOG.md`
documents why v2 exists (a fleet firmware rollout added a required
`firmware_version` field).

**Date-aware contract selection** (`load_contract_for_date` in
`src/contracts/contract.py`) is the detail that makes this actually work
in production: the pipeline validates each batch against whichever
contract version was *effective on that batch's run date*, not whichever
is newest today. Days 1-8 (before the Sept 9 rollout) are correctly
validated against v1; days 9-10 against v2 — automatically, with no
manual pipeline reconfiguration on cutover day. Publishing v2 doesn't
retroactively break yesterday's already-valid batches.

## Drift detection, not just hard schema checks

Fields flagged `drift_check: true` in a contract (temperature, vibration)
are checked with the **Population Stability Index (PSI)** — a batch can
pass every hard schema check and still get flagged if its distribution
has quietly shifted from the contract's baseline. Day 6/7 show this
escalating from unflagged → moderate → a significant-drift alert as the
simulated sensor recalibration drifts further from baseline, exactly the
"catch it before it becomes a real problem" behavior drift monitoring
exists for.

## Nothing is silently dropped

Rows that fail validation are written to `data/quarantine/*.csv` with
their specific violation reason(s) attached (`_violation_reasons`
column); rows that pass are admitted to `data/lakehouse_admitted/*.parquet`.
A human (or a follow-up pipeline) can always go look at exactly what was
rejected and why.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python scripts/simulate_batches.py   # -> data/incoming_batches/day_01.csv ... day_10.csv
python scripts/run_all_days.py       # runs the full validate -> quarantine/admit -> alert -> log pipeline

streamlit run dashboard/app.py       # -> http://localhost:8501, pass/fail + drift trend charts

pytest tests/ -v
```

To see real Slack alerts instead of the local-log fallback:
```bash
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
python scripts/run_all_days.py
```

## Airflow

`dags/data_quality_contract_pipeline` runs `@daily`:
`validate_and_admit` (calls `src/pipeline.py` for that day's batch) →
`quality_gate` (reads the trend record just written and **fails the task**
— blocking downstream consumers — if more than 5% of rows failed
validation, even though the valid rows were already safely admitted;
the gate is about whether to *trust* the batch, not whether to keep the
data).

## Key Technologies
Python, pandas, PSI-based statistical drift detection, YAML schema contracts, SQLite/Parquet, Apache Airflow, Streamlit, Slack webhook alerting

## Disclaimer
Educational/portfolio project using fully synthetic sensor data.
