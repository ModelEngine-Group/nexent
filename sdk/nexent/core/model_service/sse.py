# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Bounded incremental SSE framing shared by sync and async HTTP senders."""

import codecs
from collections.abc import Iterator
from dataclasses import dataclass, field


class SSEDecodeError(ValueError):
    """Safe framing failure with no provider payload in diagnostics."""

    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


@dataclass(frozen=True)
class SSEEvent:
    """A complete SSE frame; provider JSON interpretation belongs to adapters."""

    data: str
    event: str = "message"
    event_id: str = ""
    sensitive_values: tuple[str, ...] = field(default=(), repr=False, compare=False)


class SSEDecoder:
    """Decode UTF-8 text fragments without reconnecting or interpreting retry fields.

    Only blank-line-terminated data blocks become events. Incomplete data at EOF
    is an explicit Nexent failure rather than a successful model completion.
    """

    def __init__(self, *, max_event_bytes: int = 1024 * 1024):
        if type(max_event_bytes) is not int or max_event_bytes <= 0:
            raise ValueError("SSE event byte limit must be a positive integer")
        self._limit = max_event_bytes
        self._size = 0
        self._line: list[str] = []
        self._data: list[str] = []
        self._event = ""
        self._id = ""
        self._first = True
        self._after_cr = False
        self._closed = False

    def _fail(self, category: str) -> None:
        self._closed = True
        self._line.clear()
        self._data.clear()
        raise SSEDecodeError(category) from None

    def _consume_line(self) -> SSEEvent | None:
        line = "".join(self._line)
        self._line.clear()
        if not line:
            result = SSEEvent("\n".join(self._data), self._event or "message", self._id) if self._data else None
            self._data.clear()
            self._event = ""
            self._size = 0
            return result
        if line.startswith(":"):
            return None
        field, separator, value = line.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]
        if field == "data":
            self._data.append(value)
        elif field == "event":
            self._event = value
        elif field == "id" and "\x00" not in value:
            self._id = value
        return None

    def feed(self, fragment: str) -> Iterator[SSEEvent]:
        """Yield completed frames immediately, even before a later frame fails.

        Exhaust this iterator before feeding another fragment. HTTP iteration
        supplies already incrementally decoded UTF-8 text, never raw bytes.
        """
        if self._closed:
            raise SSEDecodeError("SSE_DECODER_CLOSED")
        if not isinstance(fragment, str):
            self._fail("SSE_INVALID_TEXT")
        for character in fragment:
            if self._first:
                self._first = False
                if character == "\ufeff":
                    continue
            if self._after_cr:
                self._after_cr = False
                if character == "\n":
                    continue
            try:
                self._size += len(character.encode("utf-8"))
            except UnicodeEncodeError:
                self._fail("SSE_INVALID_TEXT")
            if self._size > self._limit:
                self._fail("SSE_EVENT_TOO_LARGE")
            if character in ("\r", "\n"):
                self._after_cr = character == "\r"
                event = self._consume_line()
                if event is not None:
                    yield event
            else:
                self._line.append(character)

    def finish(self) -> None:
        """Close framing; provider finish markers still require adapter validation."""
        if self._closed:
            raise SSEDecodeError("SSE_DECODER_CLOSED")
        self._closed = True
        if self._line:
            self._consume_line()
        if self._data:
            self._fail("SSE_INCOMPLETE_EVENT")


class SSEByteDecoder:
    """Strict UTF-8 decoding keeps byte splits transparent and corruption explicit."""

    def __init__(self, *, max_event_bytes: int = 1024 * 1024):
        self._text = codecs.getincrementaldecoder("utf-8")()
        self._frames = SSEDecoder(max_event_bytes=max_event_bytes)

    def feed(self, fragment: bytes) -> Iterator[SSEEvent]:
        if not isinstance(fragment, bytes):
            self._frames._fail("SSE_INVALID_TEXT")
        try:
            text = self._text.decode(fragment)
        except UnicodeError:
            self._frames._fail("SSE_INVALID_TEXT")
        yield from self._frames.feed(text)

    def finish(self) -> None:
        try:
            self._text.decode(b"", final=True)
        except UnicodeError:
            self._frames._fail("SSE_INVALID_TEXT")
        self._frames.finish()
