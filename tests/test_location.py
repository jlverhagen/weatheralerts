"""Tests for the GPS-to-NWS coverage resolver."""
import asyncio
from unittest.mock import Mock

import pytest

from custom_components.weatheralerts.location import NwsPointResolver, _nws_code


class Response:
    status = 200

    def __init__(self, payload):
        self.payload = payload
        self.release = Mock()

    async def json(self):
        await asyncio.sleep(0)
        return self.payload


class Session:
    def __init__(self, response):
        self.response = response
        self.urls = []

    async def get(self, url, headers):
        self.urls.append(url)
        await asyncio.sleep(0)
        return self.response


@pytest.mark.asyncio
async def test_resolve_forecast_zone_and_county():
    session = Session(Response({"properties": {
        "forecastZone": "https://api.weather.gov/zones/forecast/WIZ038",
        "county": "https://api.weather.gov/zones/county/WIC087",
    }}))
    resolver = NwsPointResolver(session)
    a, b = await asyncio.gather(resolver.resolve(44.26, -88.41), resolver.resolve(44.26, -88.41))
    assert a == b
    assert a.feedid == "WIZ038,WIC087"
    assert len(session.urls) == 1
    assert session.response.release.call_count == 1
    await resolver.resolve(44.26, -88.41)
    assert len(session.urls) == 1


@pytest.mark.asyncio
async def test_invalid_coordinates():
    resolver = NwsPointResolver(Session(Response({})))
    with pytest.raises(ValueError):
        await resolver.resolve(95, -88)
    with pytest.raises(ValueError):
        await resolver.resolve(float("nan"), -88)
    with pytest.raises(ValueError):
        await resolver.resolve(44, float("inf"))


@pytest.mark.asyncio
async def test_unsupported_location():
    resolver = NwsPointResolver(Session(Response({"properties": {}})))
    with pytest.raises(ValueError, match="supported alert coverage"):
        await resolver.resolve(0, 0)


def test_reject_untrusted_coverage_urls():
    assert _nws_code("https://example.com/zones/forecast/WIZ038", "forecast") == ""
    assert _nws_code("https://api.weather.gov/zones/county/WIC087", "county") == "WIC087"
    assert _nws_code("https://api.weather.gov/zones/forecast/WIZ038", "county") == ""
    assert _nws_code("https://api.weather.gov/zones/forecast/WIC087", "forecast") == ""


@pytest.mark.asyncio
async def test_cancelled_gps_waiter_does_not_leave_completed_lookup():
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowSession(Session):
        async def get(self, url, headers):
            self.urls.append(url)
            started.set()
            await release.wait()
            return self.response

    session = SlowSession(Response({"properties": {
        "forecastZone": "https://api.weather.gov/zones/forecast/WIZ038",
        "county": "https://api.weather.gov/zones/county/WIC087",
    }}))
    resolver = NwsPointResolver(session)
    waiter = asyncio.create_task(resolver.resolve(44.26, -88.41))
    await started.wait()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    release.set()
    for _ in range(10):
        await asyncio.sleep(0)
    assert not resolver._inflight
    assert (await resolver.resolve(44.26, -88.41)).feedid == "WIZ038,WIC087"
    assert len(session.urls) == 1  # completed shielded request was cached


def test_reject_noncanonical_nws_coverage_urls():
    invalid = (
        "https://api.weather.gov:444/zones/forecast/WIZ038",
        "https://user@api.weather.gov/zones/forecast/WIZ038",
        "https://api.weather.gov:bad/zones/forecast/WIZ038",
        "https://[invalid/zones/forecast/WIZ038",
        "https://api.weather.gov/zones/forecast/WIZ038?extra=1",
        "https://api.weather.gov/zones/forecast/WIZ038#other",
    )
    for url in invalid:
        assert _nws_code(url, "forecast") == ""


@pytest.mark.asyncio
async def test_failed_points_lookup_does_not_cache_failure():
    response = Response({})
    response.status = 503
    session = Session(response)
    resolver = NwsPointResolver(session)
    with pytest.raises(ValueError, match="HTTP 503"):
        await resolver.resolve(44.26, -88.41)
    assert response.release.call_count == 1
    session.response = Response({"properties": {
        "forecastZone": "https://api.weather.gov/zones/forecast/WIZ038",
        "county": "https://api.weather.gov/zones/county/WIC087",
    }})
    assert (await resolver.resolve(44.26, -88.41)).feedid == "WIZ038,WIC087"
    assert len(session.urls) == 2


@pytest.mark.asyncio
async def test_points_response_without_supported_coverage_is_not_cached():
    session = Session(Response({"properties": {
        "forecastZone": "https://example.com/zones/forecast/WIZ038",
    }}))
    resolver = NwsPointResolver(session)
    with pytest.raises(ValueError, match="supported alert coverage"):
        await resolver.resolve(44.26, -88.41)
    session.response = Response({"properties": {
        "county": "https://api.weather.gov/zones/county/WIC087",
    }})
    assert (await resolver.resolve(44.26, -88.41)).feedid == "WIC087"
    assert len(session.urls) == 2
