import logging
import os
import sys

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
log = logging.getLogger("task2.gateway")

UNAUTHORIZED_TOOL_CALL = -32001

TOKEN_ROLES = {"admin-token": "admin", "viewer-token": "viewer"}


def get_role_from_token(authorization: str | None) -> str | None:
    """Return 'admin', 'viewer', or None. Never raises on a bad header."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[len("Bearer "):].strip()
    if token in TOKEN_ROLES:
        return TOKEN_ROLES[token]
    prefix = token.split(":", 1)[0]
    return prefix if prefix in ("admin", "viewer") else None

def create_app(downstream_url: str | None = None) -> FastAPI:
    downstream = (downstream_url
                  or os.environ.get("DOWNSTREAM_URL", "http://127.0.0.1:9001"))
    app = FastAPI(title="MCP Security Gateway")

    @app.get("/health")
    async def health():
        return {"status": "ok", "downstream": downstream}

    @app.post("/mcp")
    async def mcp_proxy(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"jsonrpc": "2.0", "id": None,
                 "error": {"code": -32700, "message": "Parse error"}},
                status_code=200)
        if not isinstance(body, dict) or "method" not in body:
            return JSONResponse(
                {"jsonrpc": "2.0", "id": body.get("id") if isinstance(body, dict) else None,
                 "error": {"code": -32600, "message": "Invalid Request"}},
                status_code=200)

        req_id, method = body.get("id"), body["method"]

        
        if method == "tools/call":
            params = body.get("params") or {}
            tool_name = params.get("name", "")
            if isinstance(tool_name, str) and tool_name.startswith("admin_"):
                role = get_role_from_token(request.headers.get("authorization"))
                if role != "admin":
                    log.warning("Blocked unauthorized admin tool call: %s (role=%s)",
                                tool_name, role)
                    return JSONResponse(
                        {"jsonrpc": "2.0", "id": req_id,
                         "error": {"code": UNAUTHORIZED_TOOL_CALL,
                                   "message": "Unauthorized Tool Call: "
                                              f"{tool_name} requires admin role"}},
                        status_code=200)

     
        try:
            # trust_env=False: internal service-to-service traffic must
            # never be routed through an egress HTTP proxy.
            async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
                resp = await client.post(f"{downstream.rstrip('/')}/mcp",
                                         json=body)
            return JSONResponse(content=resp.json(), status_code=200)
        except Exception as exc:  # downstream down / bad JSON: don't leak it
            log.error("Downstream error: %s", exc)
            return JSONResponse(
                {"jsonrpc": "2.0", "id": req_id,
                 "error": {"code": -32603,
                           "message": "Internal error: downstream unavailable"}},
                status_code=200)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=9000)
