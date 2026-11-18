"""Tests for dynamic NWS coverage transitions."""
from custom_components.weatheralerts.coverage_transition import (
    coverage_transition,
    initial_tracking_for_coverage,
)


def test_same_coverage_in_different_order_is_not_a_transition():
    result = coverage_transition("WIZ038,WIC087", "wic087, wiz038")
    assert not result.changed


def test_crossing_county_boundary_changes_coverage():
    result = coverage_transition("WIZ038,WIC087", "WIZ063,WIC025")
    assert result.changed
    assert result.previous_feedid == "WIC087,WIZ038"
    assert result.new_feedid == "WIC025,WIZ063"


def test_new_coverage_tracking_has_no_old_location_deletions():
    alerts = [
        {"id": "new-alert", "sent": "2026-11-18T12:00:00+00:00", "expires": "2026-11-18T14:00:00+00:00"},
        {"id": "new-alert", "sent": "2026-11-18T12:00:00+00:00", "expires": "2026-11-18T14:00:00+00:00"},
    ]
    tracking = initial_tracking_for_coverage(alerts, "2026-11-18T12:01:00+00:00")
    assert len(tracking) == 1
    assert tracking[0]["status"] == "new"
    assert tracking[0]["id"] == "new-alert"
    assert all(item["status"] != "delete" for item in tracking)


def test_missing_alert_ids_are_not_tracked():
    assert initial_tracking_for_coverage([{"id": "null"}, {"id": None}], "now") == []
