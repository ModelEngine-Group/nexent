# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Isolated SSE framing proof; actual HTTP integration belongs to MST-D3-001."""

import pytest
from nexent.core.model_service.sse import (
    SSEByteDecoder,
    SSEDecodeError,
    SSEDecoder,
    SSEEvent,
)


def decode(fragments, **options):
    decoder = SSEDecoder(**options)
    events = [event for fragment in fragments for event in decoder.feed(fragment)]
    decoder.finish()
    return events


@pytest.mark.parametrize("newline", ["\n", "\r", "\r\n"])
def test_every_fragment_boundary_preserves_unicode_and_multiline_events(newline):
    text = newline.join(
        [
            "\ufeff: heartbeat",
            "id: call-1",
            "event: delta",
            "data: 中文",
            "data:  second",
            "",
            "data",
            "",
            "",
        ]
    )
    expected = [
        SSEEvent("中文\n second", "delta", "call-1"),
        SSEEvent("", "message", "call-1"),
    ]
    for split in range(len(text) + 1):
        assert decode([text[:split], text[split:]]) == expected
    assert decode(list(text)) == expected


def test_comment_unknown_retry_and_null_id_fields_do_not_create_events():
    text = "id: retained\n\ndata: one\n\nid: ignored\x00\nevent: custom\nretry: 0\nunknown: hidden\n: data: false\ndata: two\n\nid:\ndata: three\n\n"
    assert decode([text]) == [
        SSEEvent("one", event_id="retained"),
        SSEEvent("two", "custom", "retained"),
        SSEEvent("three"),
    ]


def test_only_leading_bom_and_one_separator_space_are_removed():
    assert decode(["", "\ufeff", "data: \ufeffx  \n\n"]) == [SSEEvent("\ufeffx  ")]


@pytest.mark.parametrize(
    "suffix",
    ["data: private", "data: private\n", "data\n", "event: delta\ndata: private\r"],
)
def test_eof_never_promotes_incomplete_data_to_completed_event(suffix):
    decoder = SSEDecoder()
    assert list(decoder.feed(suffix)) == []
    with pytest.raises(SSEDecodeError, match="^SSE_INCOMPLETE_EVENT$"):
        decoder.finish()
    with pytest.raises(SSEDecodeError, match="^SSE_DECODER_CLOSED$"):
        list(decoder.feed("\n"))


@pytest.mark.parametrize(
    "text", ["", ": heartbeat", "event: delta\n", "id: final\n\n", "retry: 100"]
)
def test_eof_without_pending_data_is_safe_but_not_a_model_completion(text):
    assert decode([text]) == []


def test_byte_limit_is_per_event_and_counts_utf8_not_characters():
    text = "data: 中\n\n"
    size = len(text.encode("utf-8"))
    assert decode([text] * 100, max_event_bytes=size) == [SSEEvent("中")] * 100
    decoder = SSEDecoder(max_event_bytes=size - 1)
    with pytest.raises(SSEDecodeError, match="^SSE_EVENT_TOO_LARGE$"):
        list(decoder.feed(text))
    with pytest.raises(SSEDecodeError, match="^SSE_DECODER_CLOSED$"):
        decoder.finish()


@pytest.mark.parametrize(
    "text", [":" * 20, "event: " + "x" * 20, "unknown: " + "x" * 20]
)
def test_non_data_fields_cannot_bypass_buffer_limit(text):
    with pytest.raises(SSEDecodeError, match="^SSE_EVENT_TOO_LARGE$"):
        decode(list(text), max_event_bytes=10)


@pytest.mark.parametrize("limit", [0, -1, True, 1.0, None])
def test_invalid_byte_limits_are_rejected(limit):
    with pytest.raises(ValueError, match="positive integer"):
        SSEDecoder(max_event_bytes=limit)


@pytest.mark.parametrize("fragment", [b"data: bytes\n\n", "data: \ud800"])
def test_invalid_text_is_sanitized_and_decoder_becomes_terminal(fragment):
    decoder = SSEDecoder()
    with pytest.raises(SSEDecodeError, match="^SSE_INVALID_TEXT$") as caught:
        list(decoder.feed(fragment))
    assert caught.value.__cause__ is None
    with pytest.raises(SSEDecodeError, match="^SSE_DECODER_CLOSED$"):
        list(decoder.feed("data: ignored\n\n"))


def test_valid_event_remains_visible_before_later_failure_in_same_fragment():
    decoder = SSEDecoder(max_event_bytes=16)
    events = decoder.feed("data: first\n\ndata: " + "private" * 20)
    assert next(events) == SSEEvent("first")
    with pytest.raises(SSEDecodeError, match="^SSE_EVENT_TOO_LARGE$"):
        next(events)


def test_finished_decoder_cannot_accept_data_or_finish_again():
    decoder = SSEDecoder()
    decoder.finish()
    with pytest.raises(SSEDecodeError, match="^SSE_DECODER_CLOSED$"):
        list(decoder.feed(""))
    with pytest.raises(SSEDecodeError, match="^SSE_DECODER_CLOSED$"):
        decoder.finish()


def test_utf8_byte_splits_do_not_corrupt_multibyte_content():
    text = "\ufeffdata: 中文😀\r\n\r\n".encode()
    for split in range(len(text) + 1):
        decoder = SSEByteDecoder()
        events = list(decoder.feed(text[:split])) + list(decoder.feed(text[split:]))
        decoder.finish()
        assert events == [SSEEvent("中文😀")]


@pytest.mark.parametrize("fragment", [b"data: \xff\n\n", "not bytes"])
def test_invalid_utf8_is_an_error_and_not_replacement_characters(fragment):
    decoder = SSEByteDecoder()
    with pytest.raises(SSEDecodeError, match="^SSE_INVALID_TEXT$"):
        list(decoder.feed(fragment))
    with pytest.raises(SSEDecodeError, match="^SSE_DECODER_CLOSED$"):
        list(decoder.feed(b""))


def test_incomplete_utf8_at_eof_is_explicit_failure():
    decoder = SSEByteDecoder()
    assert list(decoder.feed(b"data: \xe4")) == []
    with pytest.raises(SSEDecodeError, match="^SSE_INVALID_TEXT$"):
        decoder.finish()
