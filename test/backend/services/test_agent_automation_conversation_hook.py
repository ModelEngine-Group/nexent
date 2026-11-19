# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import sys
import types

import pytest

from management.services.conversation import service as conversation_service


@pytest.mark.asyncio
async def test_delete_conversation_invokes_agent_automation_hook(monkeypatch):
    calls = {}

    class _Facade:
        async def on_conversation_deleted(self, conversation_id, user_id, tenant_id):
            calls["conversation_id"] = conversation_id
            calls["user_id"] = user_id
            calls["tenant_id"] = tenant_id

    facade_module = types.ModuleType("management.services.automation.service")
    facade_module.agent_automation_facade = _Facade()
    monkeypatch.setitem(sys.modules, "management.services.automation.service", facade_module)
    monkeypatch.setattr(conversation_service, "delete_conversation", lambda conversation_id, user_id: True)
    assert await conversation_service.delete_conversation_service(123, "user-1", "tenant-1") is True
    assert calls == {
        "conversation_id": 123,
        "user_id": "user-1",
        "tenant_id": "tenant-1",
    }
