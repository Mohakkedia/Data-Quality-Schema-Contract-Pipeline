"""
validator.py
--------------
Validates a pandas DataFrame batch against a SchemaContract: required
fields present, no unexpected extra fields (a schema-drift signal in its
own right), per-field type/range/allowed-value checks row-by-row, and
distributional drift checks (PSI) for fields flagged `drift_check: true`.

Returns a single structured ValidationReport — the artifact everything
else in this project (quarantine routing, alerting, the trend dashboard)
consumes. Nothing here raises on a bad batch; validation always succeeds
in the sense of producing a complete report, and the *caller* decides
what to do with a report that says the batch failed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from contract import FieldContract, SchemaContract
from drift import DriftResult, check_drift


@dataclass
class FieldViolation:
    field_name: str
    violation_type: str  # missing_required_field | unexpected_field | type_mismatch | out_of_range | invalid_enum_value | null_value
    row_indices: list[int] = field(default_factory=list)
    detail: str = ""


@dataclass
class ValidationReport:
    contract_name: str
    contract_version: int
    validated_at: str
    n_rows_total: int
    n_rows_valid: int
    n_rows_invalid: int
    violations: list[FieldViolation]
    drift_results: list[DriftResult]
    invalid_row_indices: list[int]

    @property
    def passed(self) -> bool:
        return self.n_rows_invalid == 0

    @property
    def has_significant_drift(self) -> bool:
        return any(d.severity == "significant" for d in self.drift_results)

    def to_dict(self) -> dict:
        return {
            "contract_name": self.contract_name,
            "contract_version": self.contract_version,
            "validated_at": self.validated_at,
            "n_rows_total": self.n_rows_total,
            "n_rows_valid": self.n_rows_valid,
            "n_rows_invalid": self.n_rows_invalid,
            "passed": self.passed,
            "has_significant_drift": self.has_significant_drift,
            "violations": [
                {"field_name": v.field_name, "violation_type": v.violation_type,
                 "n_rows_affected": len(v.row_indices), "detail": v.detail}
                for v in self.violations
            ],
            "drift_results": [
                {"field_name": d.field_name, "psi": d.psi, "severity": d.severity,
                 "current_mean": d.current_mean, "current_std": d.current_std,
                 "baseline_mean": d.baseline_mean, "baseline_std": d.baseline_std}
                for d in self.drift_results
            ],
        }


def _check_type(series: pd.Series, field_contract: FieldContract) -> pd.Series:
    """Returns a boolean mask, True where the value is NOT the expected type."""
    if field_contract.type == "string":
        return ~series.apply(lambda v: isinstance(v, str) or pd.isna(v))
    if field_contract.type == "integer":
        def is_int(v):
            if pd.isna(v):
                return True
            try:
                return float(v) == int(float(v))
            except (ValueError, TypeError):
                return False
        return ~series.apply(is_int)
    if field_contract.type == "float":
        def is_num(v):
            if pd.isna(v):
                return True
            try:
                float(v)
                return True
            except (ValueError, TypeError):
                return False
        return ~series.apply(is_num)
    if field_contract.type == "datetime":
        def is_dt(v):
            if pd.isna(v):
                return True
            try:
                pd.to_datetime(v)
                return True
            except Exception:
                return False
        return ~series.apply(is_dt)
    return pd.Series([False] * len(series), index=series.index)


def validate_batch(df: pd.DataFrame, contract: SchemaContract) -> ValidationReport:
    violations: list[FieldViolation] = []
    invalid_rows: set[int] = set()
    n_total = len(df)

    # 1. Missing required fields (whole-column check)
    for fname in contract.required_field_names:
        if fname not in df.columns:
            violations.append(FieldViolation(
                field_name=fname, violation_type="missing_required_field",
                row_indices=list(df.index),
                detail=f"Required field '{fname}' is absent from this batch entirely.",
            ))
            invalid_rows.update(df.index)

    # 2. Unexpected fields not in the contract (schema-drift signal)
    unexpected = set(df.columns) - set(contract.field_names)
    if unexpected:
        violations.append(FieldViolation(
            field_name=",".join(sorted(unexpected)), violation_type="unexpected_field",
            row_indices=[], detail=f"Batch contains fields not defined in contract v{contract.contract_version}: {sorted(unexpected)}",
        ))

    # 3. Per-field checks (only for fields actually present)
    for fc in contract.fields:
        if fc.name not in df.columns:
            continue
        series = df[fc.name]

        # Null check
        null_mask = series.isna()
        if fc.required and null_mask.any():
            rows = list(df.index[null_mask])
            violations.append(FieldViolation(
                field_name=fc.name, violation_type="null_value", row_indices=rows,
                detail=f"{len(rows)} row(s) have a null value in required field '{fc.name}'.",
            ))
            invalid_rows.update(rows)

        # Type check
        type_mask = _check_type(series, fc)
        if type_mask.any():
            rows = list(df.index[type_mask])
            violations.append(FieldViolation(
                field_name=fc.name, violation_type="type_mismatch", row_indices=rows,
                detail=f"{len(rows)} row(s) don't match expected type '{fc.type}' for '{fc.name}'.",
            ))
            invalid_rows.update(rows)

        # Range check (numeric fields)
        if fc.type in ("integer", "float") and (fc.min_value is not None or fc.max_value is not None):
            numeric = pd.to_numeric(series, errors="coerce")
            range_mask = pd.Series(False, index=series.index)
            if fc.min_value is not None:
                range_mask |= numeric < fc.min_value
            if fc.max_value is not None:
                range_mask |= numeric > fc.max_value
            range_mask &= ~null_mask
            if range_mask.any():
                rows = list(df.index[range_mask])
                violations.append(FieldViolation(
                    field_name=fc.name, violation_type="out_of_range", row_indices=rows,
                    detail=f"{len(rows)} row(s) outside [{fc.min_value}, {fc.max_value}] for '{fc.name}'.",
                ))
                invalid_rows.update(rows)

        # Allowed-values check (categorical fields)
        if fc.allowed_values is not None:
            invalid_enum_mask = ~series.isin(fc.allowed_values) & ~null_mask
            if invalid_enum_mask.any():
                rows = list(df.index[invalid_enum_mask])
                bad_values = sorted(set(series[invalid_enum_mask].astype(str)))
                violations.append(FieldViolation(
                    field_name=fc.name, violation_type="invalid_enum_value", row_indices=rows,
                    detail=f"{len(rows)} row(s) have values outside {fc.allowed_values}: found {bad_values}",
                ))
                invalid_rows.update(rows)

    # 4. Drift checks (numeric fields flagged drift_check, using only VALID rows)
    drift_results: list[DriftResult] = []
    valid_mask = ~df.index.isin(invalid_rows)
    for fc in contract.fields:
        if fc.drift_check and fc.name in df.columns and fc.baseline_mean is not None:
            values = pd.to_numeric(df.loc[valid_mask, fc.name], errors="coerce").dropna().to_numpy()
            if len(values) >= 5:  # need a minimal sample to compute a meaningful PSI
                drift_results.append(check_drift(fc.name, values, fc.baseline_mean, fc.baseline_std))

    n_invalid = len(invalid_rows)
    return ValidationReport(
        contract_name=contract.contract_name,
        contract_version=contract.contract_version,
        validated_at=datetime.now(timezone.utc).isoformat(),
        n_rows_total=n_total,
        n_rows_valid=n_total - n_invalid,
        n_rows_invalid=n_invalid,
        violations=violations,
        drift_results=drift_results,
        invalid_row_indices=sorted(invalid_rows),
    )
