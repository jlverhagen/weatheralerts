"""Observe Home Assistant location entities without modifying their states."""
from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from datetime import timedelta

from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval

_LOGGER = logging.getLogger(__name__)

LocationCallback = Callable[[float, float], Awaitable[None]]


def coordinates_from_state(state: State | None) -> tuple[float, float] | None:
    """Read GPS coordinates from zone.home or a device_tracker state."""
    if state is None or state.state in ("unknown", "unavailable"):
        return None
    try:
        lat = float(state.attributes["latitude"])
        lon = float(state.attributes["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


class LocationObserver:
    """Watch one location entity, serializing callbacks and ignoring stale work."""

    def __init__(
        self,
        hass: HomeAssistant,
        entity_id: str,
        on_location: LocationCallback,
        on_unavailable: Callable[[], None] | None = None,
    ) -> None:
        if entity_id != "zone.home" and not entity_id.startswith("device_tracker."):
            raise ValueError("Location source must be zone.home or a device_tracker")
        self._hass = hass
        self.entity_id = entity_id
        self._on_location = on_location
        self._on_unavailable = on_unavailable
        self._unsubscribe: Callable[[], None] | None = None
        self._unsubscribe_retry: Callable[[], None] | None = None
        self._task: asyncio.Task[None] | None = None
        self._last_coordinates: tuple[float, float] | None = None
        self._generation = 0
        self._stopped = False

    async def async_start(self) -> None:
        self._stopped = False
        if self._unsubscribe is not None:
            return
        self._unsubscribe = async_track_state_change_event(
            self._hass, [self.entity_id], self._handle_state_change
        )
        self._unsubscribe_retry = async_track_time_interval(
            self._hass, self._retry_if_needed, timedelta(minutes=5)
        )
        self._schedule(self._hass.states.get(self.entity_id))

    @callback
    def _retry_if_needed(self, now) -> None:
        # Retry an unresolved location even if the GPS entity has not changed.
        if not self._stopped and self._last_coordinates is None:
            self._schedule(self._hass.states.get(self.entity_id))

    @callback
    def _handle_state_change(self, event: Event) -> None:
        self._schedule(event.data.get("new_state"))

    @callback
    def _schedule(self, state: State | None) -> None:
        if self._stopped:
            return
        coordinates = coordinates_from_state(state)
        if coordinates is None:
            if self._last_coordinates is not None:
                self._last_coordinates = None
                self._generation += 1
                if self._task is not None:
                    self._task.cancel()
                if self._on_unavailable is not None:
                    self._on_unavailable()
            return
        if coordinates == self._last_coordinates:
            return
        self._last_coordinates = coordinates
        self._generation += 1
        generation = self._generation
        if self._task is not None:
            self._task.cancel()
        self._task = self._hass.async_create_task(
            self._dispatch(coordinates, generation)
        )

    async def _dispatch(self, coordinates: tuple[float, float], generation: int) -> None:
        try:
            await self._on_location(*coordinates)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Allow a subsequent state update with identical coordinates to retry.
            if generation == self._generation:
                self._last_coordinates = None
            _LOGGER.exception("WeatherAlerts location update failed for %s", self.entity_id)
        finally:
            if generation == self._generation:
                self._task = None

    async def async_stop(self) -> None:
        self._stopped = True
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._unsubscribe_retry is not None:
            self._unsubscribe_retry()
            self._unsubscribe_retry = None
        self._generation += 1
        self._last_coordinates = None
        if self._task is not None:
            task = self._task
            self._task = None
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
