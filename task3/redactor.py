import re

REDACTED = "[REDACTED]"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CARD_RE = re.compile(r"\b(?:\d[ \-]?){12,18}\d\b")

# Order matters: SSN first, so an SSN isn't partially eaten by the looser card pattern.
_PATTERNS = (SSN_RE, CARD_RE, EMAIL_RE)


def redact_text(text: str) -> str:
    """Redact all complete PII patterns in a finished string."""
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


_PARTIAL_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]*$")
_PARTIAL_WORD = re.compile(r"[A-Za-z0-9._%+\-]+$")
_PARTIAL_DIGITS = re.compile(r"\d[\d \-]*$")


def _partial_tail(text: str) -> str:
    """Longest trailing substring that could still become a pattern.

    Returns "" if the text ends on a safe boundary (space, punctuation
    that cannot continue a pattern, etc.).
    """
    for regex in (_PARTIAL_EMAIL, _PARTIAL_DIGITS, _PARTIAL_WORD):
        match = regex.search(text)
        if match:
            return match.group(0)
    return ""


class StreamingRedactor:
    """Stateful, chunk-at-a-time redactor."""

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, chunk: str) -> str:
        """Return the safely-emittable, redacted prefix for `chunk`."""
        self._buffer += chunk
        out_parts: list[str] = []

        while self._buffer:
            # 1. Complete pattern present?
            earliest = None  # (start, end)
            for pattern in _PATTERNS:
                match = pattern.search(self._buffer)
                if match and (earliest is None or match.start() < earliest[0]):
                    earliest = (match.start(), match.end())
            if earliest is not None:
                start, end = earliest
                # Touches the end of the buffer? It may still grow.
                if end == len(self._buffer):
                    break
                out_parts.append(self._buffer[:start])
                out_parts.append(REDACTED)
                self._buffer = self._buffer[end:]
                continue

            # 2. No complete pattern: hold only a growable tail.
            tail = _partial_tail(self._buffer)
            if tail:
                out_parts.append(self._buffer[: len(self._buffer) - len(tail)])
                self._buffer = tail
            else:
                out_parts.append(self._buffer)
                self._buffer = ""
            break

        return "".join(out_parts)

    def close(self) -> str:
        """Flush the held tail (end of stream: nothing can grow now)."""
        tail, self._buffer = self._buffer, ""
        return redact_text(tail)
