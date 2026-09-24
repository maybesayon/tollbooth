import re
from dataclasses import dataclass

_LINE_BREAK = re.compile(rb"[\r\n]")


@dataclass(frozen=True)
class SSEEvent:
    raw: bytes
    event: str | None
    data: str | None


class SSEParser:
    """Incremental Server-Sent Events parser.

    Splits a byte stream into events without buffering more than one event. Each event keeps the
    exact bytes it was parsed from, so a proxy can forward the stream unmodified. Handles CRLF, LF
    and CR line endings, and chunk boundaries anywhere (including between CR and LF).
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._scan = 0
        self._event: str | None = None
        self._data: list[str] = []

    def feed(self, chunk: bytes) -> list[SSEEvent]:
        self._buffer += chunk
        events: list[SSEEvent] = []
        while (bounds := self._next_line()) is not None:
            line_end, next_start = bounds
            line = bytes(self._buffer[self._scan : line_end])
            self._scan = next_start
            if line:
                self._parse_field(line.decode("utf-8", errors="replace"))
            else:
                events.append(self._dispatch())
        return events

    def flush(self) -> bytes:
        """Return any bytes of an unterminated trailing event."""
        rest = bytes(self._buffer)
        self._buffer.clear()
        self._scan = 0
        self._event, self._data = None, []
        return rest

    def _next_line(self) -> tuple[int, int] | None:
        match = _LINE_BREAK.search(self._buffer, self._scan)
        if match is None:
            return None
        end = match.start()
        if self._buffer[end] == ord("\n"):
            return end, end + 1
        if end + 1 == len(self._buffer):
            return None
        return end, end + 2 if self._buffer[end + 1] == ord("\n") else end + 1

    def _parse_field(self, line: str) -> None:
        if line.startswith(":"):
            return
        name, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if name == "event":
            self._event = value
        elif name == "data":
            self._data.append(value)

    def _dispatch(self) -> SSEEvent:
        raw = bytes(self._buffer[: self._scan])
        del self._buffer[: self._scan]
        self._scan = 0
        event = SSEEvent(
            raw=raw, event=self._event, data="\n".join(self._data) if self._data else None
        )
        self._event, self._data = None, []
        return event
