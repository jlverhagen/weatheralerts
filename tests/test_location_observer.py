"""Tests for Home Assistant location state coordinate extraction."""
import asyncio
import math

import pytest
from types import SimpleNamespace

from custom_components.weatheralerts.location_observer import LocationObserver, coordinates_from_state


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


@pytest.mark.asyncio
async def test_tracker_unavailable_invalidates_previous_fix():
    started = asyncio.Event()
    cancelled = asyncio.Event()
    unavailable = []

    async def on_location(lat, lon):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    hass = SimpleNamespace(async_create_task=asyncio.create_task)
    observer = LocationObserver(
        hass, "device_tracker.phone", on_location,
        on_unavailable=lambda: unavailable.append(True),
    )
    observer._schedule(state(latitude=44.26, longitude=-88.41))
    await started.wait()
    observer._schedule(state("unavailable"))
    await asyncio.wait_for(cancelled.wait(), timeout=1)
    assert unavailable == [True]
    assert observer._last_coordinates is None
    await observer.async_stop()


@pytest.mark.asyncio
async def test_stopped_observer_ignores_late_state_events():
    calls = []

    async def on_location(lat, lon):
        calls.append((lat, lon))

    hass = SimpleNamespace(async_create_task=asyncio.create_task)
    observer = LocationObserver(hass, "device_tracker.phone", on_location)
    await observer.async_stop()
    observer._schedule(state(latitude=44.26, longitude=-88.41))
    await asyncio.sleep(0)
    assert calls == []


@pytest.mark.asyncio
async def test_failed_location_callback_can_retry_same_coordinates():
    attempts = []
    finished = asyncio.Event()

    async def on_location(lat, lon):
        attempts.append((lat, lon))
        if len(attempts) == 1:
            raise RuntimeError("Temporary NWS lookup failure")
        finished.set()

    hass = SimpleNamespace(async_create_task=asyncio.create_task)
    observer = LocationObserver(hass, "device_tracker.phone", on_location)
    fix = state(latitude=44.26, longitude=-88.41)
    observer._schedule(fix)
    for _ in range(10):
        await asyncio.sleep(0)
        if observer._last_coordinates is None:
            break
    assert observer._last_coordinates is None
    observer._schedule(fix)
    await asyncio.wait_for(finished.wait(), timeout=1)
    assert attempts == [(44.26, -88.41), (44.26, -88.41)]
    await observer.async_stop()


@pytest.mark.asyncio
async def test_new_gps_fix_cancels_superseded_callback():
    first_started = asyncio.Event()
    first_cancelled = asyncio.Event()
    second_finished = asyncio.Event()
    completed = []

    async def on_location(lat, lon):
        if lat == 44.26:
            first_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                first_cancelled.set()
                raise
        completed.append((lat, lon))
        second_finished.set()

    hass = SimpleNamespace(async_create_task=asyncio.create_task)
    observer = LocationObserver(hass, "device_tracker.phone", on_location)
    observer._schedule(state(latitude=44.26, longitude=-88.41))
    await asyncio.wait_for(first_started.wait(), timeout=1)
    observer._schedule(state(latitude=43.1, longitude=-89.2))
    await asyncio.wait_for(first_cancelled.wait(), timeout=1)
    await asyncio.wait_for(second_finished.wait(), timeout=1)
    assert completed == [(43.1, -89.2)]
    assert observer._last_coordinates == (43.1, -89.2)
    await observer.async_stop()


@pytest.mark.asyncio
async def test_identical_gps_fix_does_not_repeat_successful_callback():
    calls = []
    finished = asyncio.Event()

    async def on_location(lat, lon):
        calls.append((lat, lon))
        finished.set()

    hass = SimpleNamespace(async_create_task=asyncio.create_task)
    observer = LocationObserver(hass, "device_tracker.phone", on_location)
    fix = state(latitude=44.26, longitude=-88.41)
    observer._schedule(fix)
    await asyncio.wait_for(finished.wait(), timeout=1)
    observer._schedule(fix)
    await asyncio.sleep(0)
    assert calls == [(44.26, -88.41)]
    await observer.async_stop()
