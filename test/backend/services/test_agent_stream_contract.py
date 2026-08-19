"""Tests for the shared Agent SSE interruption contract."""

import json

from services.agent_stream_contract import (
    RUN_INTERRUPTED_MESSAGE,
    _extract_json_objects_from_text,
    _is_run_interrupted_chunk,
    _is_run_interrupted_event,
    _run_interrupted_chunk,
)


def test_run_interrupted_chunk_contains_public_terminal_contract():
    chunk = _run_interrupted_chunk()
    payload = json.loads(chunk.removeprefix("data: ").strip())

    assert payload == {
        "type": "error",
        "status": "run_interrupted",
        "code": "run_interrupted",
        "content": RUN_INTERRUPTED_MESSAGE,
    }


def test_run_interrupted_event_accepts_status_or_code_only():
    assert _is_run_interrupted_event({"status": "run_interrupted"}) is True
    assert _is_run_interrupted_event({"code": "run_interrupted"}) is True
    assert _is_run_interrupted_event({"content": "run_interrupted"}) is False


def test_extract_json_objects_skips_noise_malformed_values_and_non_objects():
    text = 'noise [1, 2] {broken} {"type":"text"} trailing {"status":"done"}'

    assert _extract_json_objects_from_text(text) == [
        {"type": "text"},
        {"status": "done"},
    ]
    assert _extract_json_objects_from_text("") == []


def test_extract_json_objects_ignores_non_object_decoder_result(mocker):
    mocker.patch(
        "services.agent_stream_contract.json.JSONDecoder.raw_decode",
        return_value=(["not-an-object"], 2),
    )

    assert _extract_json_objects_from_text("{}") == []


def test_run_interrupted_chunk_detection_handles_multiple_embedded_events():
    chunk = 'data: {"type":"text"}\n\ndata: {"code":"run_interrupted"}\n\n'

    assert _is_run_interrupted_chunk(chunk) is True
    assert _is_run_interrupted_chunk('data: {"type":"text"}\n\n') is False
