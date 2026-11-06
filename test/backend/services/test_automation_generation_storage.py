# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Generation-fenced Redis calls and transactional automation message arguments."""

from unittest.mock import Mock

import pytest

from contracts.conversation import MessageRequest
from management.services.agent import run_state
from management.services.automation import conversation


@pytest.mark.asyncio
async def test_generation_reset_finish_and_cancel_use_the_same_fence(monkeypatch):
    service = run_state.RuntimeStateService()
    client = Mock()
    client.eval.return_value = 1
    monkeypatch.setattr(run_state, "RUNTIME_STATE_REDIS_URL", "redis://isolated-fixture")
    service._client = client
    await service.reset_stream_async("owner", 9, generation="77")
    args = client.eval.call_args.args
    assert "DEL" in args[0] and "HSET" in args[0]
    assert args[1:6] == (4, "runtime:stream:owner:9", "runtime:stream:done:owner:9",
                        "runtime:cancel:owner:9", "runtime:run:owner:9")
    assert args[6] == "77"
    service.mark_run_finished("owner", 9, "stopped", generation="77")
    args = client.eval.call_args.args
    assert "HGET" in args[0] and "return 0" in args[0]
    assert args[2] == "runtime:run:owner:9" and args[6:8] == ("77", "stopped")
    assert service.set_cancel_signal("owner", 9, expected_generation="77") is True
    args = client.eval.call_args.args
    assert "HGET" in args[0] and "SETEX" in args[0]
    assert args[1:5] == (2, "runtime:run:owner:9", "runtime:cancel:owner:9", "77")
    client.eval.return_value = 0
    assert service.set_cancel_signal("owner", 9, expected_generation="older") is False
    client.hset.assert_not_called()
    client.setex.assert_not_called()


def test_run_message_adapter_uses_atomic_creator_and_preserves_history(monkeypatch):
    monkeypatch.setattr(conversation, "get_conversation_history_service", lambda *a: [{"message": [
        {"message_index": 0, "role": "user", "message": "old question"},
        {"message_index": 1, "role": "assistant", "message": "old answer"},
    ]}])
    create = Mock(side_effect=[101, 102])
    monkeypatch.setattr(conversation, "create_run_message", create)
    save = Mock()
    unit = Mock()
    monkeypatch.setattr(conversation, "save_message", save)
    monkeypatch.setattr(conversation, "save_message_unit", unit)
    adapter = conversation.AutomationConversationAdapter()
    result = adapter.append_run_prompt(9, "scheduled question", "owner", "tenant", run_id=77)
    assert result["user_message_id"] == 101
    assert [item.content for item in result["history"]] == ["old question", "old answer"]
    create.assert_called_with(77, {"conversation_id": 9, "message_idx": 2,
                                   "role": "user", "content": "scheduled question"}, "owner", "tenant")
    request = MessageRequest(conversation_id=9, message_idx=3, role="assistant", message=[])
    assert adapter.append_run_assistant(request, run_id=77, user_id="owner", tenant_id="tenant") == 102
    create.assert_called_with(77, {"conversation_id": 9, "message_idx": 3, "role": "assistant",
                                   "content": "", "minio_files": request.minio_files}, "owner", "tenant")
    save.assert_not_called()
    unit.assert_not_called()
