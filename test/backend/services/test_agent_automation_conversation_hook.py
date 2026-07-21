import sys
import types

from services import conversation_management_service as conversation_service


def test_delete_conversation_invokes_agent_automation_hook(monkeypatch):
    calls = {}

    class _Facade:
        def on_conversation_deleted(self, conversation_id, user_id):
            calls["conversation_id"] = conversation_id
            calls["user_id"] = user_id

    facade_module = types.ModuleType("services.agent_automation.facade")
    facade_module.agent_automation_facade = _Facade()
    monkeypatch.setitem(sys.modules, "services.agent_automation.facade", facade_module)
    monkeypatch.setattr(conversation_service, "delete_conversation", lambda conversation_id, user_id: True)
    monkeypatch.setattr(
        conversation_service.agent_run_manager,
        "clear_conversation_context_manager",
        lambda conversation_id: calls.setdefault("cleared_conversation_id", conversation_id),
    )

    assert conversation_service.delete_conversation_service(123, "user-1") is True
    assert calls == {
        "conversation_id": 123,
        "user_id": "user-1",
        "cleared_conversation_id": 123,
    }
