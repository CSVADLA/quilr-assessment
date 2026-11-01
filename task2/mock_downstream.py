import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("task2.mock_downstream")

TOOLS = [
    {"name": "get_customer_record",
     "description": "Read a customer record",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "admin_reset_key",
     "description": "ADMIN ONLY: reset an API key",
     "inputSchema": {"type": "object", "properties": {}}},
]

app = FastAPI(title="Mock MCP server")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/mcp")
async def mcp(request: Request):
    body = await request.json()
    req_id, method, params = body.get("id"), body.get("method"), body.get("params") or {}
    log.info("Downstream received: %s", method)

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        return {"jsonrpc": "2.0", "id": req_id,
                "result": {"content": [{"type": "text",
                                        "text": f"executed {name}"}],
                           "isError": False}}
    return JSONResponse(
        {"jsonrpc": "2.0", "id": req_id,
         "error": {"code": -32601, "message": f"Method not found: {method}"}},
        status_code=200)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=9001)
