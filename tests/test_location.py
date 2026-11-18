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


@pytest.mark.asyncio
async def test_unsupported_location():
    resolver = NwsPointResolver(Session(Response({"properties": {}})))
    with pytest.raises(ValueError, match="supported alert coverage"):
        await resolver.resolve(0, 0)


def test_reject_untrusted_coverage_urls():
    assert _nws_code("https://example.com/zones/forecast/WIZ038", "forecast") == ""
    assert _nws_code("https://api.weather.gov/zones/county/WIC087", "county") == "WIC087"
    assert _nws_code("https://api.weather.gov/zones/forecast/WIZ038", "county") == ""
