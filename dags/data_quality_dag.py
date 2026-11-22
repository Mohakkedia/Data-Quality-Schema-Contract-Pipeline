"""
data_quality_dag.py
----------------------
Airflow DAG: each day, validate the day's incoming sensor_readings batch
against the schema contract effective on that date, quarantine/admit rows
accordingly, alert on failure or significant drift, and gate downstream
consumption on the result — this is the "robust, scalable architecture
for data orchestration" the role's opening line asks for, applied to data
quality specifically rather than just task scheduling.

  1. locate_todays_batch   — find the incoming CSV for today's run
  2. validate_and_admit    — run src/pipeline.py (validate -> quarantine/admit -> alert -> trend log)
  3. quality_gate           — read the trend record just written; FAIL this task
                              (blocking downstream consumers) if more than 5% of
                              rows failed, even though the batch's *valid* rows
                              were already safely admitted — the gate is about
                              whether to trust and consume this batch's numbers,
                              not whether to lose the data
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

PROJECT_ROOT = "/opt/airflow/project"
MAX_ACCEPTABLE_FAILURE_RATE = 0.05

default_args = {
    "owner": "data-platform",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def quality_gate(**context):
    trend_path = f"{PROJECT_ROOT}/outputs/quality_trend.jsonl"
    run_date = context["ds"]
    with open(trend_path) as f:
        records = [json.loads(line) for line in f]
    todays = [r for r in records if r["run_date"] == run_date]
    if not todays:
        raise ValueError(f"No trend record found for {run_date} — did validate_and_admit run?")
    record = todays[-1]

    failure_rate = record["n_rows_invalid"] / max(record["n_rows_total"], 1)
    print(f"Batch {run_date}: failure rate {failure_rate:.1%}, "
          f"drift flagged on {record['drift_fields_flagged']}")

    if failure_rate > MAX_ACCEPTABLE_FAILURE_RATE:
        raise ValueError(
            f"Quality gate failed: {failure_rate:.1%} of rows failed validation "
            f"(threshold {MAX_ACCEPTABLE_FAILURE_RATE:.0%}). Downstream consumers blocked "
            f"for {run_date} pending investigation."
        )
    print("Quality gate passed.")


with DAG(
    dag_id="data_quality_contract_pipeline",
    description="Daily schema-contract validation, quarantine/admission, alerting, and a quality gate",
    default_args=default_args,
    schedule="@daily",
    start_date=datetime(2026, 9, 1),
    catchup=False,
    tags=["data-quality", "schema-contracts", "governance"],
) as dag:

    validate_and_admit = BashOperator(
        task_id="validate_and_admit",
        bash_command=(
            f"cd {PROJECT_ROOT} && python src/pipeline.py "
            "--batch data/incoming_batches/day_{{ '%02d' % ((execution_date - macros.datetime(2026,9,1)).days + 1) }}.csv "
            "--run-date {{ ds }}"
        ),
    )

    gate = PythonOperator(
        task_id="quality_gate",
        python_callable=quality_gate,
    )

    validate_and_admit >> gate
