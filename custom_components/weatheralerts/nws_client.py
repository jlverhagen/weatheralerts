"""Shared NWS HTTP retrieval with bounded freshness and concurrent request coalescing.

This module deliberately does not own alert tracking, per-entry deduplication, or
sensor state. Those remain independent for each WeatherAlerts config entry.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Any

from .const import ALERTS_API, HEADERS


@dataclass
class _CachedResponse:
    payload: dict[str, Any]
    fetched_at: float


class SharedNwsAlertClient:
    """Reuse NWS responses for identical coverage without sharing sensor state."""

    def __init__(self, session: Any, *, cache_ttl: float = 30.0) -> None:
        if cache_ttl <= 0:
            raise ValueError("cache_ttl must be positive")
        self._session = session
        self._cache_ttl = cache_ttl
        self._cache: dict[str, _CachedResponse] = {}
        self._inflight: dict[str, asyncio.Task[dict[str, Any]]] = {}

    @staticmethod
    def coverage_key(feedid: str) -> str:
        """Normalize equivalent comma-separated zone/county feed combinations."""
        codes = {code.strip().upper() for code in feedid.split(",") if code.strip()}
        if not codes:
            raise ValueError("NWS coverage must contain at least one code")
        return ",".join(sorted(codes))

    async def fetch_alerts(self, feedid: str, *, timeout: float = 20.0) -> dict[str, Any]:
        """Fetch an active alert feed; coalesce simultaneous identical requests.

        The returned payload is not modified by this client. Callers must not
        mutate it; each coordinator should construct its own alert dictionaries.
        """
        key = self.coverage_key(feedid)
        cached = self._cache.get(key)
        if cached is not None and monotonic() - cached.fetched_at < self._cache_ttl:
            return cached.payload

        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._fetch(key, timeout))
            self._inflight[key] = task
            # A cancelled waiter must not leave a completed task cached as
            # in-flight forever. The request itself remains shielded/shared.
            task.add_done_callback(
                lambda completed, coverage=key: self._inflight.pop(coverage, None)
                if self._inflight.get(coverage) is completed else None
            )
        try:
            return await asyncio.shield(task)
        finally:
            if task.done() and self._inflight.get(key) is task:
                self._inflight.pop(key, None)

    async def _fetch(self, key: str, timeout: float) -> dict[str, Any]:
        async with asyncio.timeout(timeout):
            response = await self._session.get(ALERTS_API.format(key), headers=HEADERS)
            try:
                if response.status != 200:
                    raise NwsHttpError(response.status)
                payload = await response.json()
                if not isinstance(payload, dict):
                    raise ValueError("NWS returned a non-object JSON response")
            finally:
                response.release()
        self._cache[key] = _CachedResponse(payload, monotonic())
        return payload

    def clear(self) -> None:
        """Invalidate cached responses (in-flight requests remain shared)."""
        self._cache.clear()


class NwsHttpError(Exception):
    """Non-success HTTP status returned by the NWS API."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"NWS API returned HTTP {status}")
