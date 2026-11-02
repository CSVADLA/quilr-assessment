import asyncio
import os
import sys

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

try:  
    from .redactor import StreamingRedactor
except ImportError:  
    from redactor import StreamingRedactor


MOCK_CHUNKS = [
    "Hello, ", "thanks for ", "reaching out. ", "You can contact ",
    "john.doe@", "example.com ", "about your account. ",
    "For verification, ", "your SSN is ", "123-", "45-6789 ",
    "and your card ", "4111 ", "1111 1111 ", "1111. ",
    "We will follow up shortly.",
]


async def mock_llm_stream(prompt: str):
    """Yield token-like chunks, as a real LLM stream would."""
    for chunk in MOCK_CHUNKS:
        yield chunk
        await asyncio.sleep(0) 


class GenerateRequest(BaseModel):
    prompt: str = ""


def create_app() -> FastAPI:
    app = FastAPI(title="LLM Gateway (streaming guardrail)")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/v1/generate")
    async def generate(req: GenerateRequest):
        redactor = StreamingRedactor()

        async def stream():
            async for chunk in mock_llm_stream(req.prompt):
                if (safe := redactor.feed(chunk)):
                    yield safe
            if (tail := redactor.close()):
                yield tail

        return StreamingResponse(stream(), media_type="text/plain")

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1",
                port=int(os.environ.get("PORT", "9002")))
