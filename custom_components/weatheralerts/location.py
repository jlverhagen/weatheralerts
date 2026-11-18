"""Resolve Home Assistant GPS coordinates to NWS alert coverage.

This module does not update zone.home or any device tracker. It accepts their
reported coordinates and resolves forecast zone and county via NWS /points.
"""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from time import monotonic
from typing import Any
from urllib.parse import urlparse

from .const import HEADERS, POINTS_API


@dataclass(frozen=True)
class NwsCoverage:
    forecast_zone: str
    county: str

    @property
    def feedid(self) -> str:
        return ",".join(code for code in (self.forecast_zone, self.county) if code)


@dataclass
class _CachedPoint:
    coverage: NwsCoverage
    timestamp: float


def _nws_code(value: Any, category: str) -> str:
    """Extract a NWS code only from the expected API URL category."""
    if not isinstance(value, str):
        return ""
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != "api.weather.gov":
        return ""
    path = parsed.path.rstrip("/").split("/")
    if len(path) != 4 or path[:3] != ["", "zones", category]:
        return ""
    code = path[3].upper()
    expected_marker = "Z" if category == "forecast" else "C"
    if len(code) != 6 or not code[:2].isalpha() or code[2] != expected_marker or not code[3:].isdigit():
        return ""
    return code


class NwsPointResolver:
    """Resolve geographic coordinates, caching successes and sharing lookups."""

    def __init__(self, session: Any, *, cache_ttl: float = 3600.0) -> None:
        if cache_ttl <= 0:
            raise ValueError("cache_ttl must be positive")
        self._session = session
        self._cache_ttl = cache_ttl
        self._cache: dict[tuple[float, float], _CachedPoint] = {}
        self._inflight: dict[tuple[float, float], asyncio.Task[NwsCoverage]] = {}

    async def resolve(self, latitude: float, longitude: float, *, timeout: float = 20.0) -> NwsCoverage:
        lat, lon = float(latitude), float(longitude)
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Invalid latitude or longitude")
        # Rounding is solely for lookup caching; the returned coverage is
        # always resolved from the coordinates used for the actual request.
        key = (round(lat, 5), round(lon, 5))
        cached = self._cache.get(key)
        if cached and monotonic() - cached.timestamp < self._cache_ttl:
            return cached.coverage
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._fetch(lat, lon, timeout))
            self._inflight[key] = task
            # A superseded GPS event may cancel its waiter; clean up the
            # completed lookup independently of that cancelled coroutine.
            task.add_done_callback(
                lambda completed, point=key: self._inflight.pop(point, None)
                if self._inflight.get(point) is completed else None
            )
        try:
            result = await asyncio.shield(task)
        finally:
            if task.done() and self._inflight.get(key) is task:
                self._inflight.pop(key, None)
        if self._inflight.get(key) is None:
            self._cache[key] = _CachedPoint(result, monotonic())
        return result

    async def _fetch(self, lat: float, lon: float, timeout: float) -> NwsCoverage:
        async with asyncio.timeout(timeout):
            response = await self._session.get(POINTS_API.format(lat, lon), headers=HEADERS)
            try:
                if response.status != 200:
                    raise ValueError(f"NWS points lookup returned HTTP {response.status}")
                payload = await response.json()
            finally:
                response.release()
        properties = payload.get("properties") or {}
        forecast_zone = _nws_code(properties.get("forecastZone"), "forecast")
        county = _nws_code(properties.get("county"), "county")
        if not forecast_zone and not county:
            raise ValueError("NWS points response did not contain supported alert coverage")
        return NwsCoverage(forecast_zone=forecast_zone, county=county)
