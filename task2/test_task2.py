import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

HERE = Path(__file__).parent
GATEWAY_URL = "http://127.0.0.1:9000"
DOWNSTREAM_URL = "http://127.0.0.1:9001"


def _wait_up(url: str, timeout: float = 15.0):
    deadline = time.time() + timeout
    with httpx.Client(trust_env=False) as client:  # no egress proxy for localhost
        while time.time() < deadline:
            try:
                if client.get(f"{url}/health", timeout=1.0).status_code == 200:
                    return
            except Exception:
                time.sleep(0.2)
    raise RuntimeError(f"{url} did not start")


@pytest.fixture(scope="module")
def servers():
    down = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "task2.mock_downstream:app",
         "--host", "127.0.0.1", "--port", "9001"],
        cwd=str(HERE.parent))
    gate = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "task2.gateway:app",
         "--host", "127.0.0.1", "--port", "9000"],
        cwd=str(HERE.parent),
        env={**__import__("os").environ,
             "DOWNSTREAM_URL": DOWNSTREAM_URL})
    try:
        _wait_up(DOWNSTREAM_URL)
        _wait_up(GATEWAY_URL)
        yield
    finally:
        gate.terminate()
        down.terminate()


def _call(method, params=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(trust_env=False) as client:
        return client.post(f"{GATEWAY_URL}/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
            headers=headers, timeout=10.0).json()


def test_tools_list_forwarded_for_viewer(servers):
    out = _call("tools/list", token="viewer-token")
    assert "result" in out
    assert {t["name"] for t in out["result"]["tools"]} == {
        "get_customer_record", "admin_reset_key"}


def test_non_admin_tool_call_forwarded_for_viewer(servers):
    out = _call("tools/call", {"name": "get_customer_record", "arguments": {}},
                token="viewer-token")
    assert "executed get_customer_record" in out["result"]["content"][0]["text"]


def test_admin_tool_blocked_for_viewer_without_downstream(servers):
    out = _call("tools/call", {"name": "admin_reset_key", "arguments": {}},
                token="viewer-token")
    assert out["error"]["code"] == -32001
    assert "Unauthorized Tool Call" in out["error"]["message"]
    assert "result" not in out


def test_admin_tool_blocked_without_any_token(servers):
    out = _call("tools/call", {"name": "admin_reset_key", "arguments": {}})
    assert out["error"]["code"] == -32001


def test_admin_tool_allowed_for_admin(servers):
    out = _call("tools/call", {"name": "admin_reset_key", "arguments": {}},
                token="admin-token")
    assert "executed admin_reset_key" in out["result"]["content"][0]["text"]
