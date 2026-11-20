# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from infrastructure.agent_stream_channels import StreamingChannel
from management.services.agent.replay import CompactReplay, subscribe_shared_checkpoint


def event(kind, content, **metadata):
    return 'data: ' + json.dumps({'type': kind, 'content': content, **metadata}) + '\n\n'


def payload(chunk):
    return json.loads(chunk.removeprefix('data: ').strip())


def test_compact_replay_merges_only_adjacent_matching_text_identity():
    replay = CompactReplay()
    replay.append(event('model_output_thinking', 'first', unit_index=1))
    replay.append(event('model_output_thinking', ' second', unit_index=1))
    replay.append(event('parse', 'print(1)', unit_index=2))
    replay.append(event('model_output_thinking', 'other', unit_index=3))
    chunks, cursor = replay.read_after()
    assert [payload(c)['content'] for c in chunks] == ['first second', 'print(1)', 'other']
    replay.append(event('model_output_thinking', ' more', unit_index=3))
    replay.append(event('final_answer', 'done', answer_phase='complete'))
    newer, _ = replay.read_after(cursor)
    assert [payload(c)['content'] for c in newer] == [' more', 'done']


def test_compact_replay_preserves_control_boundaries_and_metric_events():
    replay = CompactReplay()
    original = [event('model_output_thinking', 'discard', attempt_id='old'),
                event('model_attempt_control', '', phase='rollback', attempt_id='old'),
                event('model_output_thinking', 'keep', attempt_id='retry'),
                event('token_count', '{"duration":2}'),
                event('token_count', '{"duration":3}'),
                event('final_answer', 'part', answer_phase='delta'),
                event('final_answer', 'whole', answer_phase='complete')]
    for chunk in original:
        replay.append(chunk)
    assert replay.read_after()[0] == original


@pytest.mark.asyncio
async def test_full_replay_survives_trim_and_slow_subscribers(monkeypatch):
    async def discard(**kwargs):
        return None
    monkeypatch.setattr('infrastructure.agent_stream_channels.runtime_state_service.append_stream_event_async', discard)
    monkeypatch.setattr('infrastructure.agent_stream_channels.RUNTIME_STREAM_LOCAL_REPLAY_MAX_BYTES', 128)
    channel = StreamingChannel('execution', 'owner', history_size=2)
    await channel.publish(event('parse', 'first-code', unit_index=0))
    await channel.publish(event('token_count', '{"duration":2}', unit_index=1))
    for _ in range(205):
        await channel.publish(event('model_output_thinking', 'x', unit_index=2))
    stream = channel.subscribe_with_history(include_replay_checkpoint=True)
    assert payload(await anext(stream))['content'] == 'first-code'
    for _ in range(205):
        await channel.publish(event('model_output_thinking', 'y', unit_index=2))
    await channel.publish(event('final_answer', 'complete', unit_index=3))
    channel.complete('failed')
    remaining = [payload(chunk) async for chunk in stream]
    assert remaining[0]['type'] == 'token_count'
    assert ''.join(p['content'] for p in remaining if p['type'] == 'model_output_thinking') == 'x' * 205 + 'y' * 205
    assert remaining[-1]['content'] == 'complete'
    assert channel.history_size <= 2
    assert channel.completion_status == 'failed'
    assert not channel.has_subscribers


@pytest.mark.asyncio
async def test_shared_reader_does_not_apply_the_next_runs_terminal_state():
    service = SimpleNamespace(
        get_stream_status_async=AsyncMock(return_value={"status": "completed"}),
        get_run_state_async=AsyncMock(return_value={"status": "completed", "generation": "new"}),
    )
    initial = {"generation": "old", "cursor": "1-0", "entries": [{"type": "parse", "content": "old-code"}]}
    result = [payload(chunk) async for chunk in subscribe_shared_checkpoint(service, "owner", 91, initial)]
    assert result[-1] == {"status": "stopped"}
    assert all(event.get("status") != "completed" for event in result)
