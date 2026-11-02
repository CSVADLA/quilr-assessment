import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from task4.app import create_app
from task4.router import (GatewayError, SqliteSlidingWindowLimiter,
                          UpstreamError, UpstreamResult, estimate_tokens,
                          route_completion)


def test_sliding_window_limit_and_eviction(tmp_path):
    limiter = SqliteSlidingWindowLimiter(str(tmp_path / "r.db"), limit_tokens_per_minute=100)
    assert limiter.allow("k1", 60)[0] is True
    assert limiter.allow("k1", 50)[0] is False  
    assert limiter.allow("k1", 40)[0] is True   
    assert limiter.allow("k2", 100)[0] is True
    old = time.time() - 61
    limiter._conn.execute("UPDATE rate_events SET ts = ? WHERE api_key = 'k1'", (old,))
    limiter._conn.commit()
    assert limiter.usage("k1") == 0
    assert limiter.allow("k1", 100)[0] is True


def test_denied_call_does_not_consume_budget(tmp_path):
    limiter = SqliteSlidingWindowLimiter(str(tmp_path / "r.db"), limit_tokens_per_minute=10)
    assert limiter.allow("k", 10)[0] is True
    assert limiter.allow("k", 5)[0] is False
    assert limiter.usage("k") == 10  


async def _primary_ok(prompt):
    return UpstreamResult("primary-model", f"p:{prompt}")


async def _primary_429(prompt):
    raise UpstreamError(429)


async def _primary_slow(prompt):
    await asyncio.sleep(10)
    return UpstreamResult("primary-model", "too late")


async def _secondary(prompt):
    return UpstreamResult("secondary-model", f"s:{prompt}")


async def _secondary_down(prompt):
    raise UpstreamError(503)


@pytest.mark.asyncio
async def test_primary_used_when_healthy():
    result, used = await route_completion(_primary_ok, _secondary, "hi")
    assert used == "primary" and result.text == "p:hi"


@pytest.mark.asyncio
async def test_fallback_on_429():
    result, used = await route_completion(_primary_429, _secondary, "hi")
    assert used == "secondary"


@pytest.mark.asyncio
async def test_fallback_on_timeout():
    result, used = await route_completion(_primary_slow, _secondary, "hi",
                                          timeout_seconds=0.2)
    assert used == "secondary"


@pytest.mark.asyncio
async def test_sanitised_error_when_both_fail():
    with pytest.raises(GatewayError) as excinfo:
        await route_completion(_primary_429, _secondary_down, "hi")
    payload = excinfo.value.payload()
    assert excinfo.value.status == 502
    assert payload == {"error": {"code": "UPSTREAM_UNAVAILABLE",
                                 "message": "All model providers are unavailable. "
                                            "Please retry later."}}
    assert "Traceback" not in str(payload) and "503" not in str(payload)


def test_http_rate_limit_and_fallback(tmp_path):
    client = TestClient(create_app(db_path=str(tmp_path / "r.db"), limit=100))
    ok = client.post("/v1/completions", json={"prompt": "x" * 40},
                     headers={"X-API-Key": "tenant-a"})
    assert ok.status_code == 200 and ok.json()["model_used"] == "primary"

    blocked = client.post("/v1/completions", json={"prompt": "x" * 400},
                          headers={"X-API-Key": "tenant-a"})
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"

    fallback = client.post("/v1/completions", json={
        "prompt": "hello", "primary_behaviour": "429"},
        headers={"X-API-Key": "tenant-b"})
    assert fallback.status_code == 200
    assert fallback.json()["model_used"] == "secondary"
