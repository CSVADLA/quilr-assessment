# Quilr AI — Field Developer / Solutions Engineer Assessment

Python implementations of the four assessment tasks, built and tested locally
with mock providers no LLM API or cloud cost.

## Tasks

### Task 1 — Custom MCP server (`task1/`)

A stdio MCP server with strict Pydantic validation before any business logic:
`customer_id` must match `^CUST-\d{5}$`, refund `amount > 0`, and `reason` must
be at least 10 characters. Tools: `get_customer_record`, `trigger_refund`.
Stdout carries only JSON-RPC; logs go to stderr. Invalid params return
`-32602`.

### Task 2 — MCP security gateway (`task2/`)

A proxy in front of an MCP server. `tools/list` is forwarded for any role.
`tools/call` to a non-`admin_` tool is forwarded. `tools/call` to an `admin_*`
tool from a non-admin role is blocked before any downstream call with
`-32001 Unauthorized Tool Call`. JSON-RPC errors still return HTTP 200.
Demo tokens: `Bearer admin-token` / `viewer-token` (production would verify
a JWT — the gate logic doesn't change).

### Task 3 — LLM streaming PII guardrail (`task3/`)

`POST /v1/generate` streams a response, redacting emails, SSNs, and card
numbers to `[REDACTED]` — including values split across chunks. The redactor
holds only the trailing token that could still grow, so latency stays low
and memory stays O(tail), never O(response). A new redactor is created per
request.

### Task 4 — Rate-limiting + fallback router (`task4/`)

Token-aware sliding-window limiter in SQLite (default 50,000 tokens/minute
per API key, 60 s window), plus a model fallback router. Token estimate:
`ceil(len(text) / 4)`. Denied calls insert nothing and don't consume budget.
Fallback triggers on 429, timeout (3 s, which cancels the primary), or 5xx;
other 4xx are not retried. If both providers fail, the client gets a
sanitised 502 `UPSTREAM_UNAVAILABLE` with no upstream detail.

## Run the tests

From the project root, with the virtual environment activated:

```powershell
pytest -v
```
