"""Pure helpers for dynamic WeatherAlerts coverage transitions.

A location transition must not be treated as an NWS alert cancellation:
tracking rows belong to a particular coverage area, and switching to another
area must start a fresh tracking view without emitting delete records for the
previous area's alerts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CoverageTransition:
    previous_feedid: str
    new_feedid: str
    changed: bool


def coverage_transition(previous_feedid: str, new_feedid: str) -> CoverageTransition:
    """Return the requested transition after validating its coverage codes."""
    from .nws_client import SharedNwsAlertClient

    previous = SharedNwsAlertClient.coverage_key(previous_feedid)
    new = SharedNwsAlertClient.coverage_key(new_feedid)
    return CoverageTransition(previous, new, previous != new)


def initial_tracking_for_coverage(
    alerts: list[dict[str, Any]],
    timestamp: str,
) -> list[dict[str, Any]]:
    """Create tracking rows for a new coverage area without false deletions.

    This is intentionally independent of prior-location tracking. The caller
    retains its previous tracking history separately if needed for diagnostics.
    """
    result = []
    seen = set()
    for alert in alerts:
        alert_id = alert.get("id")
        if not alert_id or alert_id == "null" or alert_id in seen:
            continue
        seen.add(alert_id)
        result.append({
            "id": alert_id,
            "sent": alert.get("sent"),
            "expires": alert.get("expires"),
            "status": "new",
            "status_timestamp": timestamp,
        })
    return sorted(result, key=lambda row: (row.get("sent") or "", row["id"]), reverse=True)
