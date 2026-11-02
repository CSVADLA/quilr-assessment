import asyncio
import os

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

try:
    from .router import (GatewayError, SqliteSlidingWindowLimiter,
                         UpstreamError, UpstreamResult, estimate_tokens,
                         route_completion)
except ImportError:
    from router import (GatewayError, SqliteSlidingWindowLimiter,
                        UpstreamError, UpstreamResult, estimate_tokens,
                        route_completion)


class CompletionRequest(BaseModel):
    prompt: str
    primary_behaviour: str = "ok"  


async def mock_primary(prompt: str, behaviour: str) -> UpstreamResult:
    if behaviour == "429":
        raise UpstreamError(429)
    if behaviour == "timeout":
        await asyncio.sleep(10)  
    return UpstreamResult(model="primary-model", text=f"[primary] {prompt}")


async def mock_secondary(prompt: str) -> UpstreamResult:
    return UpstreamResult(model="secondary-model", text=f"[secondary] {prompt}")


def create_app(db_path: str | None = None,
               limit: int | None = None) -> FastAPI:
    limiter = SqliteSlidingWindowLimiter(
        db_path or os.environ.get("RATE_LIMIT_DB", "rate_limit.db"),
        limit_tokens_per_minute=limit
        or int(os.environ.get("RATE_LIMIT_TOKENS_PER_MINUTE", "50000")))
    app = FastAPI(title="LLM Gateway Router")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/v1/completions")
    async def completions(req: CompletionRequest,
                          x_api_key: str | None = Header(default="demo-key")):
        tokens = estimate_tokens(req.prompt)
        allowed, used = limiter.allow(x_api_key, tokens)
        if not allowed:
            return JSONResponse(
                {"error": {"code": "RATE_LIMITED",
                           "message": "Token rate limit exceeded. Please retry later."}},
                status_code=429)
        try:
            result, model_used = await route_completion(
                lambda p: mock_primary(p, req.primary_behaviour),
                mock_secondary, req.prompt)
        except GatewayError as exc:
            return JSONResponse(exc.payload(), status_code=exc.status)
        return {"model_used": model_used, "text": result.text,
                "usage_tokens": tokens,
                "rate_limit": {"used": used, "limit": limiter.limit}}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=9003)
