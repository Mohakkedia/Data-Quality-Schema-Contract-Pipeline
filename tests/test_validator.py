import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "contracts"))

import numpy as np
import pandas as pd

from contract import load_contract, load_contract_for_date
from drift import check_drift, compute_psi
from validator import validate_batch

CONTRACTS_DIR = ROOT / "contracts"


def test_v1_contract_loads_correctly():
    c = load_contract(CONTRACTS_DIR / "sensor_readings_v1.yaml")
    assert c.contract_version == 1
    assert "firmware_version" not in c.field_names
    assert "temperature_c" in c.required_field_names


def test_v2_contract_requires_firmware_version():
    c = load_contract(CONTRACTS_DIR / "sensor_readings_v2.yaml")
    assert c.contract_version == 2
    assert "firmware_version" in c.required_field_names


def test_date_aware_contract_selection():
    before = load_contract_for_date(CONTRACTS_DIR, "sensor_readings", "2026-09-01")
    assert before.contract_version == 1
    after = load_contract_for_date(CONTRACTS_DIR, "sensor_readings", "2026-09-09")
    assert after.contract_version == 2


def _clean_df(n=50):
    return pd.DataFrame({
        "line_id": np.random.choice(["LINE-01", "LINE-02"], n),
        "timestamp": pd.date_range("2026-09-01", periods=n, freq="min").astype(str),
        "temperature_c": np.random.normal(70, 6, n),
        "vibration_mm_s": np.random.normal(0.85, 0.15, n),
        "throughput_units_min": np.random.randint(30, 50, n),
    })


def test_clean_batch_passes():
    contract = load_contract(CONTRACTS_DIR / "sensor_readings_v1.yaml")
    df = _clean_df()
    report = validate_batch(df, contract)
    assert report.passed
    assert report.n_rows_invalid == 0


def test_missing_required_field_fails_all_rows():
    contract = load_contract(CONTRACTS_DIR / "sensor_readings_v1.yaml")
    df = _clean_df().drop(columns=["vibration_mm_s"])
    report = validate_batch(df, contract)
    assert not report.passed
    assert any(v.violation_type == "missing_required_field" for v in report.violations)


def test_out_of_range_value_detected():
    contract = load_contract(CONTRACTS_DIR / "sensor_readings_v1.yaml")
    df = _clean_df()
    df.loc[0, "temperature_c"] = 999.0  # way out of [0, 150]
    report = validate_batch(df, contract)
    assert not report.passed
    assert 0 in report.invalid_row_indices


def test_invalid_enum_value_detected():
    contract = load_contract(CONTRACTS_DIR / "sensor_readings_v1.yaml")
    df = _clean_df()
    df.loc[0, "line_id"] = "LINE-99"  # not in allowed_values
    report = validate_batch(df, contract)
    assert not report.passed
    assert any(v.violation_type == "invalid_enum_value" for v in report.violations)


def test_unexpected_field_flagged_without_failing_batch():
    contract = load_contract(CONTRACTS_DIR / "sensor_readings_v1.yaml")
    df = _clean_df()
    df["firmware_version"] = "v2.4.0"  # not in v1 contract
    report = validate_batch(df, contract)
    # unexpected_field is a signal, not a row-level failure by itself
    assert any(v.violation_type == "unexpected_field" for v in report.violations)


def test_psi_near_zero_for_identical_distribution():
    np.random.seed(0)
    values = np.random.normal(70, 6, 500)
    psi = compute_psi(values, baseline_mean=70, baseline_std=6)
    assert psi < 0.1


def test_psi_high_for_shifted_distribution():
    np.random.seed(0)
    values = np.random.normal(90, 6, 500)  # shifted 20 degrees from baseline
    psi = compute_psi(values, baseline_mean=70, baseline_std=6)
    assert psi > 0.25


def test_drift_check_classifies_severity():
    np.random.seed(0)
    values = np.random.normal(90, 6, 500)
    result = check_drift("temperature_c", values, baseline_mean=70, baseline_std=6)
    assert result.severity == "significant"


if __name__ == "__main__":
    test_v1_contract_loads_correctly()
    test_v2_contract_requires_firmware_version()
    test_date_aware_contract_selection()
    test_clean_batch_passes()
    test_missing_required_field_fails_all_rows()
    test_out_of_range_value_detected()
    test_invalid_enum_value_detected()
    test_unexpected_field_flagged_without_failing_batch()
    test_psi_near_zero_for_identical_distribution()
    test_psi_high_for_shifted_distribution()
    test_drift_check_classifies_severity()
    print("All tests passed.")
