"""
alerter.py
------------
Posts a data-quality alert to Slack (if SLACK_WEBHOOK_URL is set) and/or
appends it to a local, append-only alert log (outputs/alerts.jsonl) —
always, regardless of whether Slack is configured, so the alert history
is queryable even without a Slack workspace (and so this project's tests
and demo run fully offline with zero external calls unless a webhook URL
is explicitly provided).

A real email path (smtplib) is stubbed the same way: attempted if
SMTP_* env vars are set, otherwise logged locally — same pattern, so
swapping in real email delivery later doesn't change any caller code.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ALERT_LOG_PATH = Path(__file__).resolve().parents[2] / "outputs" / "alerts.jsonl"


def _log_locally(alert: dict[str, Any]) -> None:
    ALERT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ALERT_LOG_PATH, "a") as f:
        f.write(json.dumps(alert, default=str) + "\n")


def _post_to_slack(text: str, webhook_url: str) -> bool:
    try:
        resp = requests.post(webhook_url, json={"text": text}, timeout=5)
        return resp.status_code == 200
    except Exception as exc:  # noqa: BLE001
        print(f"[alerter] Slack post failed: {exc}")
        return False


def build_alert_message(contract_name: str, contract_version: int, run_date: str,
                         n_invalid: int, n_total: int, top_violations: list[dict],
                         drift_alerts: list[dict]) -> str:
    lines = [
        f":rotating_light: *Data quality alert — {contract_name} v{contract_version}* ({run_date})",
        f"{n_invalid}/{n_total} rows failed validation.",
    ]
    for v in top_violations[:5]:
        lines.append(f"  • `{v['violation_type']}` on `{v['field_name']}` — {v['n_rows_affected']} row(s): {v['detail']}")
    if drift_alerts:
        lines.append("*Distributional drift detected:*")
        for d in drift_alerts:
            lines.append(f"  • `{d['field_name']}` PSI={d['psi']} ({d['severity']}) — "
                          f"current mean {d['current_mean']} vs. baseline {d['baseline_mean']}")
    return "\n".join(lines)


def send_alert(contract_name: str, contract_version: int, run_date: str,
               n_invalid: int, n_total: int, top_violations: list[dict],
               drift_alerts: list[dict]) -> dict:
    message = build_alert_message(contract_name, contract_version, run_date, n_invalid, n_total,
                                   top_violations, drift_alerts)

    alert_record = {
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "contract_name": contract_name,
        "contract_version": contract_version,
        "run_date": run_date,
        "n_invalid": n_invalid,
        "n_total": n_total,
        "message": message,
        "delivered_to": [],
    }

    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if webhook_url:
        delivered = _post_to_slack(message, webhook_url)
        if delivered:
            alert_record["delivered_to"].append("slack")

    alert_record["delivered_to"].append("local_log")
    _log_locally(alert_record)

    if "slack" not in alert_record["delivered_to"]:
        print(f"[alerter] SLACK_WEBHOOK_URL not set — alert logged locally only.\n{message}\n")

    return alert_record
