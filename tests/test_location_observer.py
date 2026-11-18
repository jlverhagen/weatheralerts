"""Tests for Home Assistant location state coordinate extraction."""
import math
from types import SimpleNamespace

from custom_components.weatheralerts.location_observer import coordinates_from_state


def state(value="home", **attributes):
    return SimpleNamespace(state=value, attributes=attributes)


def test_valid_home_coordinates():
    assert coordinates_from_state(state(latitude=44.26, longitude=-88.41)) == (44.26, -88.41)


def test_valid_tracker_coordinates_when_state_is_zone_name():
    assert coordinates_from_state(state("work", latitude="43.1", longitude="-89.2")) == (43.1, -89.2)


def test_unavailable_tracker_is_ignored():
    assert coordinates_from_state(state("unavailable", latitude=44.0, longitude=-88.0)) is None


def test_missing_or_invalid_coordinates_are_ignored():
    assert coordinates_from_state(state(latitude=44.0)) is None
    assert coordinates_from_state(state(latitude=math.nan, longitude=-88.0)) is None
    assert coordinates_from_state(state(latitude=100.0, longitude=-88.0)) is None
