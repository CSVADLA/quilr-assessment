from fastapi.testclient import TestClient

from task3.gateway_stream import create_app
from task3.redactor import StreamingRedactor, redact_text


def test_redact_text_complete_patterns():
    out = redact_text("mail john.doe@example.com, ssn 123-45-6789, "
                      "card 4111 1111 1111 1111, ok")
    assert "john.doe@example.com" not in out
    assert "123-45-6789" not in out
    assert "4111" not in out
    assert out.count("[REDACTED]") == 3
    assert out.endswith(", ok")


def test_split_across_chunks_is_still_redacted():
    redactor = StreamingRedactor()
    out = ""
    for chunk in ["mail john.doe@", "example.com, ssn 123-", "45-6789, ",
                  "card 4111 111", "1 1111 1111, done"]:
        out += redactor.feed(chunk)
    out += redactor.close()
    assert "john.doe" not in out and "123-45-6789" not in out
    assert "4111" not in out
    assert out.count("[REDACTED]") == 3
    assert out.endswith(", done")


def test_streaming_does_not_buffer_everything():
    """Ordinary words must be emitted before the stream ends."""
    redactor = StreamingRedactor()
    first = redactor.feed("Hello world, this is ")
    assert first   
    assert "Hello" in first


def test_endpoint_streams_redacted_output():
    client = TestClient(create_app())
    with client.stream("POST", "/v1/generate", json={"prompt": "hi"}) as resp:
        assert resp.status_code == 200
        chunks = list(resp.iter_text())
    body = "".join(chunks)
    assert "john.doe@example.com" not in body
    assert "123-45-6789" not in body
    assert "4111" not in body
    assert body.count("[REDACTED]") == 3
    assert "thanks for reaching out" in body
    assert len(chunks) > 1
