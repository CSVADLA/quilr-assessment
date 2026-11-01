import json
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError

HERE = Path(__file__).parent
SERVER = HERE / "server.py"


@pytest.mark.asyncio
async def test_tools_list_and_valid_calls():
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert names == {"get_customer_record", "trigger_refund"}

            ok = await session.call_tool(
                "get_customer_record", {"customer_id": "CUST-00001"})
            assert not ok.isError
            assert "Asha Rao" in ok.content[0].text

            refund = await session.call_tool(
                "trigger_refund",
                {"customer_id": "CUST-00001", "amount": 25.5,
                 "reason": "Defective item returned"})
            assert not refund.isError
            assert "REF-" in refund.content[0].text


@pytest.mark.asyncio
async def test_invalid_inputs_are_rejected():
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            bad_calls = [
                ("get_customer_record", {"customer_id": "12345"}),
                ("get_customer_record", {"customer_id": "CUST-123"}),
                ("get_customer_record", {"customer_id": "CUST-123456"}),
                ("trigger_refund", {"customer_id": "CUST-00001",
                                    "amount": -5, "reason": "long enough reason"}),
                ("trigger_refund", {"customer_id": "CUST-00001",
                                    "amount": 0, "reason": "long enough reason"}),
                ("trigger_refund", {"customer_id": "CUST-00001",
                                    "amount": 10, "reason": "too short"}),
                ("trigger_refund", {"customer_id": "CUST-00001",
                                    "amount": "ten", "reason": "long enough reason"}),
            ]
            for name, args in bad_calls:
                try:
                    result = await session.call_tool(name, args)
                except McpError as exc:
                    assert exc.error.code == -32602, (name, args, exc.error)
                else:
                    assert result.isError, (name, args, result)


def test_stdout_is_pure_jsonrpc():
    """Send a raw initialize request; the first stdout line must be JSON."""
    proc = subprocess.Popen(
        [sys.executable, str(SERVER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True)
    try:
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05",
                       "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
        }) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        payload = json.loads(line)  # raises if stdout was polluted
        assert payload["jsonrpc"] == "2.0" and payload["id"] == 1
    finally:
        proc.kill()
