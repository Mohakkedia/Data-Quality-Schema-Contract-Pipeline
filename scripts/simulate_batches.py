"""
simulate_batches.py
----------------------
Generates 10 days of incoming `sensor_readings` batches, deliberately
varied so the resulting pass/fail/drift trend tells a real story rather
than being uniformly clean:

  Day 1-3   Clean batches, v1 contract shape.
  Day 4     A producer bug: ~15% of rows have a null vibration_mm_s reading.
  Day 5     Clean again.
  Day 6-7   Gradual sensor recalibration drift: temperature readings trend
            a few degrees warmer than baseline (not yet contract-breaking,
            but should trip the PSI drift check).
  Day 8     A bad deploy: throughput_units_min sent as a string ("forty-two")
            for a subset of rows — a type_mismatch violation.
  Day 9     The fleet firmware rollout completes: batch now includes
            `firmware_version`, shaped for contract v2, NOT v1 — this is
            the "unexpected_field" schema-drift signal if validated
            against v1, and should validate cleanly against v2.
  Day 10    Clean, v2-shaped.

Output: data/incoming_batches/day_NN.csv (one file per day)
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)
LINES = ["LINE-01", "LINE-02", "LINE-03", "LINE-04"]
ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "incoming_batches"
OUT_DIR.mkdir(parents=True, exist_ok=True)

START_DATE = date(2026, 9, 1)
N_ROWS_PER_DAY = 200


def base_batch(day_idx: int, temp_shift: float = 0.0) -> pd.DataFrame:
    d = START_DATE + timedelta(days=day_idx)
    rows = []
    for i in range(N_ROWS_PER_DAY):
        line = RNG.choice(LINES)
        ts = f"{d.isoformat()}T{(i % 24):02d}:{(i * 7) % 60:02d}:00Z"
        rows.append({
            "line_id": line,
            "timestamp": ts,
            "temperature_c": round(float(RNG.normal(70 + temp_shift, 6)), 2),
            "vibration_mm_s": round(float(RNG.normal(0.85, 0.15)), 3),
            "throughput_units_min": int(RNG.normal(42, 4)),
        })
    return pd.DataFrame(rows)


def main():
    for day_idx in range(10):
        day_num = day_idx + 1
        if day_num in (1, 2, 3, 5):
            df = base_batch(day_idx)
        elif day_num == 4:
            df = base_batch(day_idx)
            null_idx = RNG.choice(df.index, size=int(0.15 * len(df)), replace=False)
            df.loc[null_idx, "vibration_mm_s"] = None
        elif day_num in (6, 7):
            # Gradual recalibration drift: +3C on day 6, +5.5C on day 7
            shift = 3.0 if day_num == 6 else 5.5
            df = base_batch(day_idx, temp_shift=shift)
        elif day_num == 8:
            df = base_batch(day_idx)
            bad_idx = RNG.choice(df.index, size=10, replace=False)
            df["throughput_units_min"] = df["throughput_units_min"].astype(object)
            df.loc[bad_idx, "throughput_units_min"] = "forty-two"
        elif day_num == 9:
            df = base_batch(day_idx)
            df["firmware_version"] = RNG.choice(["v2.4.0", "v2.4.1"], size=len(df))
        elif day_num == 10:
            df = base_batch(day_idx)
            df["firmware_version"] = RNG.choice(["v2.4.0", "v2.4.1"], size=len(df))
        else:
            df = base_batch(day_idx)

        out_path = OUT_DIR / f"day_{day_num:02d}.csv"
        df.to_csv(out_path, index=False)
        print(f"Wrote {out_path} ({len(df)} rows)")


if __name__ == "__main__":
    main()
