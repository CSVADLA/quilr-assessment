import math
import sqlite3
import threading
import time
import asyncio
from dataclasses import dataclass

WINDOW_SECONDS = 60.0
DEFAULT_LIMIT_TOKENS_PER_MINUTE = 50_000
DEFAULT_TIMEOUT_SECONDS = 3.0


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token). Documented approximation."""
    return max(1, math.ceil(len(text) / 4))


class SqliteSlidingWindowLimiter:
    def __init__(self, db_path: str,
                 limit_tokens_per_minute: int = DEFAULT_LIMIT_TOKENS_PER_MINUTE,
                 window_seconds: float = WINDOW_SECONDS):
        self.limit = limit_tokens_per_minute
        self.window = window_seconds
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS rate_events ("
            "  api_key TEXT NOT NULL, ts REAL NOT NULL, tokens INTEGER NOT NULL)")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rate_key_ts "
            "ON rate_events (api_key, ts)")
        self._conn.commit()

    def _evict(self, api_key: str, now: float) -> None:
        self._conn.execute(
            "DELETE FROM rate_events WHERE api_key = ? AND ts <= ?",
            (api_key, now - self.window))

    def usage(self, api_key: str, now: float | None = None) -> int:
        now = time.time() if now is None else now
        with self._lock:
            self._evict(api_key, now)
            row = self._conn.execute(
                "SELECT COALESCE(SUM(tokens), 0) FROM rate_events "
                "WHERE api_key = ?", (api_key,)).fetchone()
            self._conn.commit()
            return int(row[0])

    def allow(self, api_key: str, tokens: int,
              now: float | None = None) -> tuple[bool, int]:
        """Return (allowed, usage_after_this_call_or_current_usage).

        A denied call inserts nothing, so a client hammering the
        limiter does not inflate its own usage.
        """
        now = time.time() if now is None else now
        with self._lock:
            self._evict(api_key, now)
            used = int(self._conn.execute(
                "SELECT COALESCE(SUM(tokens), 0) FROM rate_events "
                "WHERE api_key = ?", (api_key,)).fetchone()[0])
            if used + tokens > self.limit:
                self._conn.commit()
                return False, used
            self._conn.execute(
                "INSERT INTO rate_events (api_key, ts, tokens) VALUES (?, ?, ?)",
                (api_key, now, tokens))
            self._conn.commit()
            return True, used + tokens

@dataclass
class UpstreamResult:
    model: str
    text: str


class UpstreamError(Exception):
    """An upstream failure, with only a status the router may act on."""

    def __init__(self, status: int):
        super().__init__(f"upstream error {status}")
        self.status = status


class GatewayError(Exception):
    """Sanitised, client-safe gateway failure. No upstream detail."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def payload(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


async def route_completion(primary, secondary, prompt: str,
                           timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
                           ) -> tuple[UpstreamResult, str]:
    """Try primary, fall back to secondary on 429 / timeout / 5xx.

    `primary` / `secondary` are async callables `(prompt) -> UpstreamResult`.
    Returns `(result, model_used)` where model_used is "primary"
    or "secondary". Raises `GatewayError` only when both fail.
    """
    try:
        result = await asyncio.wait_for(primary(prompt), timeout=timeout_seconds)
        return result, "primary"
    except asyncio.TimeoutError:
        pass  
    except UpstreamError as exc:
        if exc.status != 429 and not (500 <= exc.status < 600):
            raise GatewayError(400, "UPSTREAM_REJECTED",
                               "Request was rejected by the model provider.")
    except Exception:
        pass

    try:
        result = await asyncio.wait_for(secondary(prompt), timeout=timeout_seconds)
        return result, "secondary"
    except Exception:
        raise GatewayError(
            502, "UPSTREAM_UNAVAILABLE",
            "All model providers are unavailable. Please retry later.") from None
