# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Incremental JSON scalar decoding without materializing large OTLP strings."""

from __future__ import annotations

import codecs
import hashlib
import json
import math
import os
import re

from .trajectory_io import TrajectoryCorrupt

SPECIAL = re.compile(rb'["\\\x00-\x1f]')
PREVIEW_BYTES = 16 * 1024


class TrajectoryReadBudgetExceeded(RuntimeError):
    """A valid input can exceed the reader's bounded memory or value budget."""


class Text(str):
    """A bounded preview with source coordinates and decoded lengths."""

    def __new__(cls, preview, *, start, end, byte_count, char_count, digest=None):
        obj = super().__new__(cls, preview)
        obj.start, obj.end = start, end
        obj.byte_count, obj.char_count = byte_count, char_count
        obj.digest = digest
        return obj


class JSONReader:
    """Use a fixed input buffer, depth/value limits and a bounded preview budget."""

    def __init__(self, fd, length, *, start=0, buffer_size=65536, check=None):
        self.fd, self.length, self.pos = fd, length, start
        self.buffer_size, self.check = buffer_size, check or (lambda: None)
        self.buffer, self.index = b"", 0
        self.values, self.retained = 0, 0

    def peek(self):
        if self.index == len(self.buffer) and self.pos < self.length:
            self.check()
            self.buffer = os.pread(
                self.fd, min(self.buffer_size, self.length - self.pos), self.pos
            )
            self.index = 0
            if not self.buffer:
                raise TrajectoryCorrupt("Confirmed JSON prefix is missing")
        return (
            self.buffer[self.index : self.index + 1] if self.pos < self.length else b""
        )

    def take(self):
        value = self.peek()
        if not value:
            raise TrajectoryCorrupt("Unexpected end of JSON")
        self.index += 1
        self.pos += 1
        return value

    def whitespace(self):
        while self.peek() and self.peek() in b" \t\r\n":
            self.take()

    def string_parts(self):
        if self.take() != b'"':
            raise TrajectoryCorrupt("Expected a JSON string")
        decoder = codecs.getincrementaldecoder("utf8")("strict")
        while True:
            if not self.peek():
                raise TrajectoryCorrupt("Unterminated JSON string")
            match = SPECIAL.search(self.buffer, self.index)
            end = match.start() if match else len(self.buffer)
            if end > self.index:
                raw = self.buffer[self.index : end]
                self.pos += len(raw)
                self.index = end
                text = decoder.decode(raw)
                if text:
                    yield text
                continue
            byte = self.take()
            if byte == b'"':
                tail = decoder.decode(b"", final=True)
                if tail:
                    yield tail
                return
            if byte != b"\\":
                raise TrajectoryCorrupt("Unescaped JSON control character")
            decoder.decode(b"", final=True)
            decoder.reset()
            escape = self.take()
            if escape == b"u":
                code = self._unicode()
                if 0xD800 <= code <= 0xDBFF:
                    if self.take() != b"\\" or self.take() != b"u":
                        raise TrajectoryCorrupt("Unpaired JSON surrogate")
                    low = self._unicode()
                    if not 0xDC00 <= low <= 0xDFFF:
                        raise TrajectoryCorrupt("Invalid JSON surrogate pair")
                    code = 0x10000 + ((code - 0xD800) << 10) + low - 0xDC00
                elif 0xDC00 <= code <= 0xDFFF:
                    raise TrajectoryCorrupt("Unpaired JSON surrogate")
                yield chr(code)
            else:
                decoded = {
                    b'"': '"',
                    b"\\": "\\",
                    b"/": "/",
                    b"b": "\b",
                    b"f": "\f",
                    b"n": "\n",
                    b"r": "\r",
                    b"t": "\t",
                }.get(escape)
                if decoded is None:
                    raise TrajectoryCorrupt("Invalid JSON escape")
                yield decoded

    def _unicode(self):
        raw = b"".join(self.take() for _ in range(4))
        if not re.fullmatch(rb"[0-9a-fA-F]{4}", raw):
            raise TrajectoryCorrupt("Invalid JSON unicode escape")
        return int(raw, 16)

    def string(self):
        start = self.pos
        preview, size, chars, kept = [], 0, 0, 0
        preview_full = False
        digest = hashlib.sha256()
        for part in self.string_parts():
            encoded = part.encode("utf8")
            digest.update(encoded)
            size += len(encoded)
            chars += len(part)
            if not preview_full and kept < PREVIEW_BYTES:
                prefix = encoded[: PREVIEW_BYTES - kept].decode("utf8", errors="ignore")
                preview.append(prefix)
                kept += len(prefix.encode())
                preview_full = len(prefix.encode()) < len(encoded)
        self.retained += kept
        if self.retained > 16 * 1024 * 1024:
            raise TrajectoryReadBudgetExceeded("JSON preview budget exceeded")
        return Text(
            "".join(preview),
            start=start,
            end=self.pos,
            byte_count=size,
            char_count=chars,
            digest=digest.hexdigest(),
        )

    def value(self, depth=0):
        self.whitespace()
        self.values += 1
        if self.values > 500_000:
            raise TrajectoryReadBudgetExceeded("JSON value budget exceeded")
        if depth > 64:
            raise TrajectoryCorrupt("JSON structure budget exceeded")
        first = self.peek()
        if first == b'"':
            return self.string()
        if first in (b"{", b"["):
            self.take()
            obj = {} if first == b"{" else []
            closing = b"}" if first == b"{" else b"]"
            self.whitespace()
            if self.peek() == closing:
                self.take()
                return obj
            while True:
                if first == b"{":
                    self.whitespace()
                    key = self.string()
                    if key.byte_count > 1024 or key in obj:
                        raise TrajectoryCorrupt("Invalid or duplicate JSON key")
                    self.whitespace()
                    if self.take() != b":":
                        raise TrajectoryCorrupt("Expected JSON colon")
                    obj[str(key)] = self.value(depth + 1)
                else:
                    obj.append(self.value(depth + 1))
                self.whitespace()
                separator = self.take()
                if separator == closing:
                    return obj
                if separator != b",":
                    raise TrajectoryCorrupt("Invalid JSON separator")
        token = bytearray()
        while self.peek() and self.peek() not in b",]} \t\r\n":
            token.extend(self.take())
            if len(token) > 128:
                raise TrajectoryCorrupt("Invalid JSON scalar")
        try:
            result = json.loads(
                token, parse_constant=lambda _: (_ for _ in ()).throw(ValueError())
            )
            if isinstance(result, (list, dict, str)) or (
                isinstance(result, float) and not math.isfinite(result)
            ):
                raise ValueError()
            return result
        except (ValueError, TypeError, UnicodeError) as exc:
            raise TrajectoryCorrupt("Invalid JSON scalar") from exc

    def requests(self):
        while True:
            self.whitespace()
            if not self.peek():
                return
            self.retained = self.values = 0
            yield self.value()


def read_text(fd, start, end, *, offset=0, limit=1024 * 1024, check=None):
    """Select decoded UTF-8 bytes, returning only whole Unicode codepoints."""
    if (
        type(offset) is not int
        or offset < 0
        or type(limit) is not int
        or not 4 <= limit <= 1024 * 1024
    ):
        raise ValueError("Invalid text range")
    reader = JSONReader(fd, end, start=start, check=check)
    position, chars, parts, selected = 0, 0, [], 0
    for text in reader.string_parts():
        encoded = text.encode("utf8")
        following = position + len(encoded)
        if following > offset and selected < limit:
            local = max(0, offset - position)
            try:
                tail = encoded[local:].decode("utf8")
            except UnicodeError as exc:
                raise ValueError("Text offset splits a codepoint") from exc
            prefix = tail.encode()[: limit - selected].decode("utf8", errors="ignore")
            parts.append(prefix)
            selected += len(prefix.encode())
            if len(prefix.encode()) < len(tail.encode()):
                break
        position = following
        chars += len(text)
        if selected >= limit:
            break
    if position < offset and selected == 0:
        raise ValueError("Text offset exceeds source")
    return {"text": "".join(parts), "offset": offset, "next_offset": offset + selected}
