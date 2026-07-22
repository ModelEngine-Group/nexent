import json

from services.agent_automation import conversation_adapter as adapter_module
from services.agent_automation.conversation_adapter import AutomationConversationAdapter


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

    def fake_save_message(request, user_id, tenant_id):
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
