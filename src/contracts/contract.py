"""
contract.py
-------------
Loads a versioned YAML schema contract (see ../../contracts/*.yaml) into a
structured Python object the validator can check a DataFrame against.
Contracts are plain data, not code — this is deliberate: a data producer
or governance team can review/approve a contract change by reading a
small YAML diff, without needing to read Python.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class FieldContract:
    name: str
    type: str
    required: bool = True
    allowed_values: list[Any] | None = None
    min_value: float | None = None
    max_value: float | None = None
    drift_check: bool = False
    baseline_mean: float | None = None
    baseline_std: float | None = None


@dataclass
class SchemaContract:
    contract_name: str
    contract_version: int
    effective_date: str
    fields: list[FieldContract]
    primary_key: list[str] = field(default_factory=list)
    supersedes: int | None = None

    @property
    def required_field_names(self) -> list[str]:
        return [f.name for f in self.fields if f.required]

    @property
    def field_names(self) -> list[str]:
        return [f.name for f in self.fields]

    def get_field(self, name: str) -> FieldContract | None:
        return next((f for f in self.fields if f.name == name), None)


def load_contract(path: str | Path) -> SchemaContract:
    raw = yaml.safe_load(Path(path).read_text())
    fields = [FieldContract(**f) for f in raw["fields"]]
    return SchemaContract(
        contract_name=raw["contract_name"],
        contract_version=raw["contract_version"],
        effective_date=raw["effective_date"],
        fields=fields,
        primary_key=raw.get("primary_key", []),
        supersedes=raw.get("supersedes"),
    )


def load_latest_contract(contracts_dir: str | Path, contract_name: str) -> SchemaContract:
    """Load the highest contract_version YAML file matching contract_name
    in a directory of versioned contract files."""
    contracts_dir = Path(contracts_dir)
    candidates = []
    for p in contracts_dir.glob(f"{contract_name}_v*.yaml"):
        c = load_contract(p)
        if c.contract_name == contract_name:
            candidates.append(c)
    if not candidates:
        raise FileNotFoundError(f"No contract found for '{contract_name}' in {contracts_dir}")
    return max(candidates, key=lambda c: c.contract_version)


def load_contract_for_date(contracts_dir: str | Path, contract_name: str, as_of_date: str) -> SchemaContract:
    """Load the contract version that was in effect on `as_of_date`
    (YYYY-MM-DD): the highest-versioned contract whose effective_date is
    on or before as_of_date. This is what a real pipeline should do —
    validating a batch against 'whatever the latest contract happens to
    be today' would incorrectly fail old batches the moment a new
    contract version is published, even though they were valid when
    produced."""
    contracts_dir = Path(contracts_dir)
    candidates = []
    for p in contracts_dir.glob(f"{contract_name}_v*.yaml"):
        c = load_contract(p)
        if c.contract_name == contract_name and c.effective_date <= as_of_date:
            candidates.append(c)
    if not candidates:
        raise FileNotFoundError(
            f"No contract for '{contract_name}' was effective on or before {as_of_date} in {contracts_dir}"
        )
    return max(candidates, key=lambda c: c.contract_version)
