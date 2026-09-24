import pytest

from tollbooth.proxy.sse import SSEEvent, SSEParser

STREAM = (
    b'event: message_start\r\ndata: {"a": 1}\r\n\r\n'
    b": keep-alive comment\n\n"
    b"data: line one\ndata:line two\n\n"
    b"data: caf\xc3\xa9\r\r"
    b"data: [DONE]\n\n"
)


def _parse_in_chunks(stream: bytes, size: int) -> tuple[list[SSEEvent], bytes]:
    parser = SSEParser()
    events: list[SSEEvent] = []
    for i in range(0, len(stream), size):
        events.extend(parser.feed(stream[i : i + size]))
    return events, parser.flush()


def test_parses_events() -> None:
    events, rest = _parse_in_chunks(STREAM, len(STREAM))
    assert rest == b""
    assert [(e.event, e.data) for e in events] == [
        ("message_start", '{"a": 1}'),
        (None, None),
        (None, "line one\nline two"),
        (None, "café"),
        (None, "[DONE]"),
    ]


@pytest.mark.parametrize("size", [1, 2, 3, 5, 7, 16])
def test_any_chunking_gives_identical_events_and_bytes(size: int) -> None:
    whole, _ = _parse_in_chunks(STREAM, len(STREAM))
    events, rest = _parse_in_chunks(STREAM, size)
    assert events == whole
    assert b"".join(e.raw for e in events) + rest == STREAM


def test_every_split_point() -> None:
    whole, _ = _parse_in_chunks(STREAM, len(STREAM))
    for split in range(len(STREAM) + 1):
        parser = SSEParser()
        events = parser.feed(STREAM[:split]) + parser.feed(STREAM[split:])
        assert events == whole, split


def test_trailing_cr_waits_for_possible_lf() -> None:
    parser = SSEParser()
    assert parser.feed(b"data: x\r\n\r") == []
    [event] = parser.feed(b"\n")
    assert event.raw == b"data: x\r\n\r\n"


def test_unterminated_event_is_flushed_raw() -> None:
    parser = SSEParser()
    assert parser.feed(b"data: partial") == []
    assert parser.flush() == b"data: partial"
