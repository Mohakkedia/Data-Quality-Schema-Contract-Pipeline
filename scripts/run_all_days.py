"""
run_all_days.py
------------------
Runs every simulated daily batch (data/incoming_batches/day_NN.csv)
through the validate -> quarantine/admit -> alert -> trend-log pipeline,
in date order, resetting the trend log and alert log first so a re-run
produces a clean, reproducible trend history.

Run:
    python scripts/run_all_days.py
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "contracts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "alerting"))

from pipeline import process_batch, TREND_LOG_PATH  # noqa: E402
from alerter import ALERT_LOG_PATH  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BATCHES_DIR = ROOT / "data" / "incoming_batches"
START_DATE = date(2026, 9, 1)


def main():
    # Reset trend + alert logs and prior admitted/quarantine output for a clean re-run
    if TREND_LOG_PATH.exists():
        TREND_LOG_PATH.unlink()
    if ALERT_LOG_PATH.exists():
        ALERT_LOG_PATH.unlink()
    for d in [ROOT / "data" / "lakehouse_admitted", ROOT / "data" / "quarantine"]:
        if d.exists():
            for f in d.glob("*"):
                f.unlink()

    batch_files = sorted(BATCHES_DIR.glob("day_*.csv"))
    for i, batch_path in enumerate(batch_files):
        run_date = (START_DATE + timedelta(days=i)).isoformat()
        result = process_batch(batch_path, run_date)
        status = "PASS" if result["passed"] else "FAIL"
        drift_note = f", drift on {result['drift_fields_flagged']}" if result["drift_fields_flagged"] else ""
        print(f"[{run_date}] contract v{result['contract_version_used']} — {status} "
              f"({result['n_rows_valid']}/{result['n_rows_total']} valid){drift_note}")

    print(f"\nTrend log: {TREND_LOG_PATH}")
    print(f"Alert log: {ALERT_LOG_PATH}")


if __name__ == "__main__":
    main()
