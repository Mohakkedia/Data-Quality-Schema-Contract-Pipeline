"""
drift.py
----------
Statistical drift detection for numeric fields flagged `drift_check: true`
in a contract. Uses the Population Stability Index (PSI) — a standard,
interpretable drift metric widely used in data/ML monitoring — comparing
the current batch's distribution against the contract's stored baseline
(mean/std, used here to generate reference bin edges/expected proportions
via a normal approximation, which is a reasonable and transparent choice
for sensor telemetry that is genuinely approximately normal in-spec).

PSI interpretation (industry-standard thresholds):
  < 0.1        no significant drift
  0.1 - 0.25   moderate drift — worth a note, not urgent
  > 0.25       significant drift — should trigger an alert
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class DriftResult:
    field_name: str
    psi: float
    severity: str  # none | moderate | significant
    current_mean: float
    current_std: float
    baseline_mean: float
    baseline_std: float


def _normal_bin_edges(mean: float, std: float, n_bins: int = 10) -> np.ndarray:
    """Bin edges at equal-probability quantiles of N(mean, std), so each
    baseline bin holds ~1/n_bins of the expected mass — the standard PSI
    binning approach."""
    quantiles = np.linspace(0, 1, n_bins + 1)[1:-1]
    from scipy.stats import norm
    edges = norm.ppf(quantiles, loc=mean, scale=std)
    return np.concatenate([[-np.inf], edges, [np.inf]])


def compute_psi(current_values: np.ndarray, baseline_mean: float, baseline_std: float,
                 n_bins: int = 10) -> float:
    if len(current_values) == 0:
        return 0.0
    edges = _normal_bin_edges(baseline_mean, baseline_std, n_bins)
    expected_prop = np.full(n_bins, 1.0 / n_bins)  # equal-probability bins by construction

    actual_counts, _ = np.histogram(current_values, bins=edges)
    actual_prop = actual_counts / max(len(current_values), 1)

    # Avoid log(0) / div-by-0 with a small epsilon, standard PSI practice
    eps = 1e-4
    expected_prop = np.clip(expected_prop, eps, None)
    actual_prop = np.clip(actual_prop, eps, None)

    psi = float(np.sum((actual_prop - expected_prop) * np.log(actual_prop / expected_prop)))
    return round(psi, 4)


def classify_psi(psi: float) -> str:
    if psi >= 0.25:
        return "significant"
    if psi >= 0.10:
        return "moderate"
    return "none"


def check_drift(field_name: str, current_values: np.ndarray,
                 baseline_mean: float, baseline_std: float) -> DriftResult:
    psi = compute_psi(current_values, baseline_mean, baseline_std)
    return DriftResult(
        field_name=field_name,
        psi=psi,
        severity=classify_psi(psi),
        current_mean=round(float(np.mean(current_values)), 3) if len(current_values) else 0.0,
        current_std=round(float(np.std(current_values)), 3) if len(current_values) else 0.0,
        baseline_mean=baseline_mean,
        baseline_std=baseline_std,
    )
