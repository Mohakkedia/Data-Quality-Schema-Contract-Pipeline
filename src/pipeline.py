"""
pipeline.py
-------------
Processes one incoming daily batch end-to-end:

  1. Load the batch CSV.
  2. Validate against the LATEST contract version for its dataset.
  3. Split rows: valid rows are admitted to the "lakehouse" (data/lakehouse_admitted/),
     invalid rows are quarantined (data/quarantine/) with their specific violation
     reasons attached, so nothing is silently dropped.
  4. If the batch failed validation or showed significant drift, send an alert.
  5. Append a summary record to outputs/quality_trend.jsonl — the log the
     dashboard reads to show pass/fail/drift trends over time.

Usage:
    python src/pipeline.py --batch data/incoming_batches/day_04.csv --run-date 2026-09-04
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "contracts"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "alerting"))

from contract import load_contract_for_date  # noqa: E402
from validator import validate_batch  # noqa: E402
from alerter import send_alert  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = ROOT / "contracts"
ADMITTED_DIR = ROOT / "data" / "lakehouse_admitted"
QUARANTINE_DIR = ROOT / "data" / "quarantine"
TREND_LOG_PATH = ROOT / "outputs" / "quality_trend.jsonl"
DATASET_NAME = "sensor_readings"


def process_batch(batch_path: str | Path, run_date: str) -> dict:
    df = pd.read_csv(batch_path)
    contract = load_contract_for_date(CONTRACTS_DIR, DATASET_NAME, run_date)
    report = validate_batch(df, contract)

    ADMITTED_DIR.mkdir(parents=True, exist_ok=True)
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)

    valid_df = df.drop(index=report.invalid_row_indices, errors="ignore")
    invalid_df = df.loc[df.index.isin(report.invalid_row_indices)].copy()

    if len(valid_df):
        valid_df.to_parquet(ADMITTED_DIR / f"{run_date}.parquet", index=False)
    if len(invalid_df):
        # Attach the specific violation reason(s) for each quarantined row
        reasons_by_row: dict[int, list[str]] = {}
        for v in report.violations:
            for idx in v.row_indices:
                reasons_by_row.setdefault(idx, []).append(f"{v.violation_type}:{v.field_name}")
        invalid_df["_violation_reasons"] = invalid_df.index.map(
            lambda i: "; ".join(reasons_by_row.get(i, ["unknown"]))
        )
        invalid_df.to_csv(QUARANTINE_DIR / f"{run_date}_quarantined.csv", index=False)

    alert_sent = False
    if not report.passed or report.has_significant_drift:
        top_violations = sorted(
            report.to_dict()["violations"], key=lambda v: -v["n_rows_affected"]
        )
        drift_alerts = [d for d in report.to_dict()["drift_results"] if d["severity"] != "none"]
        send_alert(
            contract_name=contract.contract_name, contract_version=contract.contract_version,
            run_date=run_date, n_invalid=report.n_rows_invalid, n_total=report.n_rows_total,
            top_violations=top_violations, drift_alerts=drift_alerts,
        )
        alert_sent = True

    trend_record = {
        "run_date": run_date,
        "batch_file": str(batch_path),
        "contract_version_used": contract.contract_version,
        **{k: v for k, v in report.to_dict().items() if k not in ("violations", "drift_results")},
        "n_violations": len(report.violations),
        "violation_types": sorted({v.violation_type for v in report.violations}),
        "drift_fields_flagged": [d["field_name"] for d in report.to_dict()["drift_results"] if d["severity"] != "none"],
        "alert_sent": alert_sent,
    }

    TREND_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TREND_LOG_PATH, "a") as f:
        f.write(json.dumps(trend_record, default=str) + "\n")

    return trend_record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", required=True)
    parser.add_argument("--run-date", required=True)
    args = parser.parse_args()

    result = process_batch(args.batch, args.run_date)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
