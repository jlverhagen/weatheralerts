"""Unit tests for the shared NWS retrieval foundation."""
import asyncio
from unittest.mock import Mock

import pytest

from custom_components.weatheralerts.nws_client import NwsHttpError, SharedNwsAlertClient


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status = status
        self.payload = payload if payload is not None else {"features": []}
        self.release = Mock()

    async def json(self):
        await asyncio.sleep(0)
        return self.payload


class FakeSession:
    def __init__(self, response=None):
        self.response = response or FakeResponse()
        self.calls = []

    async def get(self, url, headers):
        self.calls.append(url)
        await asyncio.sleep(0)
        return self.response


@pytest.mark.asyncio
async def test_equivalent_coverage_uses_one_request():
    session = FakeSession()
    client = SharedNwsAlertClient(session)
    a, b = await asyncio.gather(
        client.fetch_alerts("WIZ038,WIC087"),
        client.fetch_alerts(" wic087 , wiz038 , WIZ038"),
    )
    assert a == b == {"features": []}
    assert len(session.calls) == 1
    assert session.response.release.call_count == 1


@pytest.mark.asyncio
async def test_cached_result_reused():
    session = FakeSession()
    client = SharedNwsAlertClient(session)
    await client.fetch_alerts("WIZ038")
    await client.fetch_alerts("WIZ038")
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_cache_invalidation():
    session = FakeSession()
    client = SharedNwsAlertClient(session)
    await client.fetch_alerts("WIZ038")
    client.clear()
    await client.fetch_alerts("WIZ038")
    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_failure_does_not_poison_cache():
    session = FakeSession(FakeResponse(status=503))
    client = SharedNwsAlertClient(session)
    with pytest.raises(NwsHttpError) as error:
        await client.fetch_alerts("WIZ038")
    assert error.value.status == 503
    session.response = FakeResponse()
    await client.fetch_alerts("WIZ038")
    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_different_coverage_is_independent():
    session = FakeSession()
    client = SharedNwsAlertClient(session)
    await asyncio.gather(client.fetch_alerts("WIZ038"), client.fetch_alerts("WIZ063"))
    assert len(session.calls) == 2


def test_empty_coverage_rejected():
    with pytest.raises(ValueError):
        SharedNwsAlertClient.coverage_key(" , ")


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_leave_completed_inflight_request():
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowSession(FakeSession):
        async def get(self, url, headers):
            self.calls.append(url)
            started.set()
            await release.wait()
            return self.response

    session = SlowSession()
    client = SharedNwsAlertClient(session)
    waiter = asyncio.create_task(client.fetch_alerts("WIZ038"))
    await started.wait()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    release.set()
    # Let the shielded fetch and its cleanup callback finish.
    for _ in range(10):
        await asyncio.sleep(0)
    assert not client._inflight
    assert await client.fetch_alerts("WIZ038") == {"features": []}
    assert len(session.calls) == 1
