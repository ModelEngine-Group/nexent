# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from contextlib import contextmanager
from types import SimpleNamespace

from management.services.automation import agent_identity as agent_identity_adapter


def test_resolve_agent_display_names_uses_user_facing_name(monkeypatch):
    rows = [
        SimpleNamespace(
            agent_id=3,
            version_no=0,
            name="weather_query_assistant",
            display_name="天气查询助手",
            tenant_id="tenant",
        ),
        SimpleNamespace(
            agent_id=3,
            version_no=4,
            name="weather_query_assistant",
            display_name="天气查询助手 v4",
            tenant_id="tenant",
        ),
    ]

    class FakeResult:
        def all(self):
            return rows

    class FakeSession:
        def execute(self, statement):
            return FakeResult()

    @contextmanager
    def fake_get_db_session():
        yield FakeSession()

    monkeypatch.setattr(
        agent_identity_adapter,
        "get_db_session",
        fake_get_db_session,
    )

    resolved = agent_identity_adapter.resolve_agent_display_names(
        [(3, 4), (3, 99)],
        "tenant",
    )

    assert resolved == {
        (3, 4): "天气查询助手 v4",
        (3, 99): "天气查询助手",
    }
