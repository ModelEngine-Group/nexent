# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import json

import pytest

from management.db.conversation.prepared_turn import PreparedTurnConflict, SavedUserTurn

from management.services.automation import conversation as adapter_module
from management.services.automation.conversation import AutomationConversationAdapter


def test_preparation_retry_loads_only_history_before_the_recorded_source(mocker):
    source = mocker.patch.object(adapter_module, "read_saved_user_turn_by_id", return_value=SavedUserTurn(31, 8, "AUTOMATION"))
    mocker.patch.object(adapter_module, "get_conversation_history_service", return_value=[{"message": [
        {"role": "user", "message_index": 0, "message": "question"},
        {"role": "assistant", "message_index": 1, "message": "old answer"},
        {"role": "assistant", "message_index": 1, "message": "latest answer"},
        {"role": "user", "message_id": 20, "message": "unindexed older question"},
        {"role": "user", "message_index": 8, "message": "persisted instruction"},
        {"role": "assistant", "message_index": 9, "message": "later answer"},
    ]}])
    save = mocker.patch.object(adapter_module, "save_message", side_effect=AssertionError("second source"))
    unit = mocker.patch.object(adapter_module, "save_message_unit", side_effect=AssertionError("second prompt unit"))
    turn = AutomationConversationAdapter().load_run_prompt(100, 31, "persisted instruction", "user", "tenant")
    source.assert_called_once_with(100, "user", "tenant", 31, "persisted instruction", None)
    assert turn["user_message_id"] == 31 and turn["assistant_message_index"] == 9
    assert [(item.role, item.content) for item in turn["history"]] == [
        ("user", "question"), ("assistant", "latest answer"), ("user", "unindexed older question"),
    ]
    save.assert_not_called()
    unit.assert_not_called()


@pytest.mark.parametrize("wrong_origin", [False, True])
def test_source_retry_rejects_unknown_order_or_non_automation_message(mocker, wrong_origin):
    mocker.patch.object(adapter_module, "read_saved_user_turn_by_id", return_value=SavedUserTurn(
        31, 8, "CHAT" if wrong_origin else "AUTOMATION",
    ))
    mocker.patch.object(adapter_module, "get_conversation_history_service", return_value=[{"message": [
        {"role": "user", "message": "unscoped history"},
    ]}])
    save = mocker.patch.object(adapter_module, "save_message")
    with pytest.raises(PreparedTurnConflict):
        AutomationConversationAdapter().load_run_prompt(100, 31, "persisted instruction", "user", "tenant")
    save.assert_not_called()


def test_run_prompt_appends_new_message_to_existing_conversation(monkeypatch):
    captured = {"units": []}
    monkeypatch.setattr(
        adapter_module,
        "get_conversation_history_service",
        lambda conversation_id, user_id: [{"message": [
            {
                "role": "user",
                "message_index": 0,
                "message": [{"type": "string", "content": "原始请求"}],
            },
            {
                "role": "assistant",
                "message_index": 1,
                "message": [{"type": "automation_proposal", "content": "hidden"}],
            },
            {
                "role": "assistant",
                "message_index": 3,
                "message": [{"type": "final_answer", "content": "上次结果"}],
            },
        ]}],
    )

    def fake_save_message(request, user_id, tenant_id, **kwargs):
        captured["message_source"] = kwargs.get("message_source")
        captured["request"] = request
        captured["owner"] = (user_id, tenant_id)
        return 31

    monkeypatch.setattr(adapter_module, "save_message", fake_save_message)
    monkeypatch.setattr(
        adapter_module,
        "save_message_unit",
        lambda **kwargs: captured["units"].append(kwargs),
    )

    adapter = AutomationConversationAdapter()
    turn = adapter.append_run_prompt(
        321,
        "整理一份项目周报",
        "user",
        "tenant",
    )

    assert turn["user_message_id"] == 31
    assert turn["assistant_message_index"] == 5
    assert [(item.role, item.content) for item in turn["history"]] == [
        ("user", "原始请求"),
        ("assistant", "上次结果"),
    ]
    assert captured["request"].conversation_id == 321
    assert captured["request"].message_idx == 4
    assert captured["request"].role == "user"
    assert captured["message_source"] == "AUTOMATION"
    assert captured["request"].message[0].content == "整理一份项目周报"
    assert captured["owner"] == ("user", "tenant")
    assert captured["units"][0]["unit_type"] == "automation_prompt"


def test_history_uses_latest_message_for_each_regenerated_index():
    history = AutomationConversationAdapter._history_items([
        {
            "role": "user",
            "message_index": 0,
            "message": "原始问题",
        },
        {
            "role": "user",
            "message_index": 0,
            "message": "原始问题",
        },
        {
            "role": "assistant",
            "message_index": 1,
            "message": [{"type": "final_answer", "content": "旧回答"}],
        },
        {
            "role": "assistant",
            "message_index": 1,
            "message": [{"type": "final_answer", "content": "最新回答"}],
        },
    ])

    assert [(item.role, item.content) for item in history] == [
        ("user", "原始问题"),
        ("assistant", "最新回答"),
    ]


def test_consecutive_runs_allocate_independent_turn_indexes(monkeypatch):
    messages = [
        {"role": "user", "message_index": 0, "message": "创建每日任务"},
        {
            "role": "assistant",
            "message_index": 1,
            "message": [{"type": "automation_proposal", "content": "proposal"}],
        },
    ]
    captured_indexes = []

    monkeypatch.setattr(
        adapter_module,
        "get_conversation_history_service",
        lambda *args: [{"message": list(messages)}],
    )

    def fake_save_message(request, user_id, tenant_id, **kwargs):
        captured_indexes.append(request.message_idx)
        messages.append({
            "role": request.role,
            "message_index": request.message_idx,
            "message": [unit.model_dump() for unit in request.message],
        })
        return 100 + len(captured_indexes)

    monkeypatch.setattr(adapter_module, "save_message", fake_save_message)
    monkeypatch.setattr(adapter_module, "save_message_unit", lambda **kwargs: None)

    adapter = AutomationConversationAdapter()
    first_turn = adapter.append_run_prompt(321, "查询当天运势", "user", "tenant")
    messages.append({
        "role": "assistant",
        "message_index": 3,
        "message": [{"type": "final_answer", "content": "第一次结果"}],
    })
    second_turn = adapter.append_run_prompt(321, "查询当天运势", "user", "tenant")

    assert captured_indexes == [2, 4]
    assert first_turn["user_message_id"] == 101
    assert second_turn["user_message_id"] == 102
    assert [item.content for item in second_turn["history"]] == [
        "创建每日任务",
        "查询当天运势",
        "第一次结果",
    ]


def test_first_run_in_empty_conversation_starts_at_zero(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        adapter_module,
        "get_conversation_history_service",
        lambda *args: [],
    )
    monkeypatch.setattr(
        adapter_module,
        "save_message",
        lambda request, user_id, tenant_id, **kwargs: captured.setdefault("request", request) and 31,
    )
    monkeypatch.setattr(adapter_module, "save_message_unit", lambda **kwargs: None)

    turn = AutomationConversationAdapter().append_run_prompt(
        321,
        "查询当天运势",
        "user",
        "tenant",
    )

    assert turn["user_message_id"] == 31
    assert turn["history"] == []
    assert captured["request"].message_idx == 0


def test_append_proposal_exchange_persists_user_instruction_and_assistant_card(monkeypatch):
    captured = {"requests": [], "units": []}
    monkeypatch.setattr(
        adapter_module,
        "get_conversation_history_service",
        lambda conversation_id, user_id: [{"message": [
            {"role": "user"},
            {"role": "assistant"},
            {"role": "assistant"},
        ]}],
    )

    def fake_save_message(request, user_id, tenant_id, **kwargs):
        captured["message_source"] = kwargs.get("message_source")
        captured["requests"].append(request)
        return 30 + len(captured["requests"])

    def fake_save_message_unit(**kwargs):
        captured["units"].append(kwargs)
        return 40 + len(captured["units"])

    monkeypatch.setattr(adapter_module, "save_message", fake_save_message)
    monkeypatch.setattr(adapter_module, "save_message_unit", fake_save_message_unit)

    refs = AutomationConversationAdapter().append_proposal_exchange(
        100,
        "每周发一个周报",
        {"proposal_id": 7, "task": {"title": "周报"}},
        "user",
        "tenant",
    )

    assert refs == {
        "user_message_id": 31,
        "user_unit_id": 41,
        "message_id": 32,
        "unit_id": 42,
    }
    assert captured["requests"][0].role == "user"
    assert captured["requests"][0].message_idx == 2
    assert captured["units"][0]["unit_type"] == "string"
    assert captured["units"][0]["unit_content"] == "每周发一个周报"
    assert captured["requests"][1].role == "assistant"
    assert captured["requests"][1].message_idx == 3
    assert captured["units"][1]["unit_type"] == "automation_proposal"
    assert json.loads(captured["units"][1]["unit_content"])["proposal_id"] == 7


def test_update_proposal_updates_persisted_unit(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        adapter_module,
        "update_unit_content",
        lambda unit_id, content, user_id: captured.update({
            "unit_id": unit_id,
            "content": content,
            "user_id": user_id,
        }),
    )

    AutomationConversationAdapter().update_proposal(
        41,
        {"proposal_id": 7, "confirmed_task_id": 9},
        "user",
    )

    assert captured["unit_id"] == 41
    assert json.loads(captured["content"])["confirmed_task_id"] == 9
