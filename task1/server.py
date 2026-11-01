import logging 
import json
import uuid
import anyio
import sys

from pydantic import BaseModel, Field, ValidationError
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData, TextContent, Tool

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
log = logging.getLogger("task1_mcp_server")

CUSTOMER_ID_RE = r"^CUST-\d{5}$"

class CustomerId(BaseModel):
    customer_id: str = Field(pattern=CUSTOMER_ID_RE)

class RefundRequest(BaseModel):
    customer_id: str = Field(pattern=CUSTOMER_ID_RE)
    amount: float = Field(gt=0)
    reason:str = Field(min_length=10)

INVALID_PARAMS = -32602

CUSTOMERS = {
    "CUST-00001": {"customer_id": "CUST-00001", "name": "Asha Rao",
                   "email": "asha@example.com", "tier": "gold"},
    "CUST-00002": {"customer_id": "CUST-00002", "name": "Ben Carter",
                   "email": "ben@example.com", "tier": "standard"},
}

def _validate(model_cls, args: dict):
    if not isinstance(args, dict):
        raise McpError(ErrorData(code=INVALID_PARAMS,
                                 message="Invalid params: argument must be a JSON object"))

    try: return model_cls.model_validate(args)
    except ValidationError as exc:
        details = ': '.join(
            f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()
        )
        raise McpError(ErrorData(code=INVALID_PARAMS,
                                 message=f"Invalid params: {details}")) from exc

server = Server("customer-mco-server")

@server.list_tools()
async def list_tools() -> list[Tool]:
    return[
        Tool(
            name="get_customer_record",
            description="Return the record for a customer ID (CUST-XXXXX).",
            inputSchema=CustomerId.model_json_schema(),
        ),
        Tool(
            name="trigger_refund",
            description="Trigger a refund for a customer.",
            inputSchema=RefundRequest.model_json_schema()
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "get_customer_record":
        req = _validate(CustomerId, arguments)
        record = CUSTOMERS.get(req.customer_id)
        if record is None:
            return [TextContent(type="text",
                                text=f"Customer not found: {req.customer_id}")]
        return [TextContent(type="text", text=json.dumps(record))]

    if name == "trigger_refund":
        req = _validate(RefundRequest, arguments)
        if req.customer_id not in CUSTOMERS:
            return [TextContent(type="text",
                                text=f"Customer not found: {req.customer_id}")]
        refund_id = f"REF-{uuid.uuid4().hex[:8].upper()}"
        log.info("Refund %s for %s amount=%.2f", refund_id,
                 req.customer_id, req.amount)  # -> stderr only
        return [TextContent(type="text", text=json.dumps({
            "refund_id": refund_id, "customer_id": req.customer_id,
            "amount": req.amount, "reason": req.reason, "status": "triggered",
        }))]

    raise McpError(ErrorData(code=INVALID_PARAMS,
                             message=f"Invalid params: unknown tool: {name}"))


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    anyio.run(main)




