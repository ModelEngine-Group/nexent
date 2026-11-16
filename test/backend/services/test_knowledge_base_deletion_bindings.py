# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Local knowledge-base deletion runs best-effort binding cleanup after storage deletion."""

import logging
from unittest.mock import AsyncMock, MagicMock

from management.db import client as db_client
from management.services.knowledge_base import management as local_management
import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("delete_fails,failed_step", [
    (False, None), (True, None), (False, "tool"), (False, "conversation"), (False, "commit"),
])
async def test_local_binding_cleanup_failure_does_not_fail_deletion(monkeypatch, caplog, delete_fails, failed_step):
    cls = local_management.KnowledgeBaseManagementService
    events = []
    session = MagicMock()
    if failed_step == "commit":
        session.commit.side_effect = RuntimeError("cleanup failed")
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(db_client.db_client, "session_maker", lambda: session)
    monkeypatch.setattr(local_management, "get_db_session", db_client.get_db_session)
    monkeypatch.setattr(cls, "_assert_knowledge_base_delete_allowed", lambda _: [])
    monkeypatch.setattr(cls, "_delete_kb_source_objects", AsyncMock(return_value={
        "deleted_count": 0, "failed_count": 0,
    }))
    monkeypatch.setattr(local_management, "get_redis_service", MagicMock())

    async def delete_index(*args):
        events.append("deleted")
        if delete_fails:
            raise RuntimeError("ES failed")
        return {"success": True}

    def clean(step):
        def run(db_session, *, index_names):
            assert db_session is session
            assert index_names == ["idx-1"]
            events.append(step)
            if step == failed_step:
                raise RuntimeError("cleanup failed")
        return run

    monkeypatch.setattr(cls, "delete_index", staticmethod(delete_index))
    for step in ("tool", "conversation"):
        monkeypatch.setattr(local_management, ("remove_tool_knowledge_references" if step == "tool" else f"remove_{step}_knowledge_bindings"), clean(step))
    if delete_fails:
        with pytest.raises(RuntimeError, match="ES failed"):
            await cls.full_delete_knowledge_base("idx-1", MagicMock(), "u1")
        session.commit.assert_not_called()
        assert events == ["deleted"]
        session.rollback.assert_not_called()
    else:
        result = await cls.full_delete_knowledge_base("idx-1", MagicMock(), "u1")
        assert result["status"] == "success"
        expected = ["deleted", "tool", "conversation"]
        if failed_step:
            assert events == (expected if failed_step == "commit" else expected[:expected.index(failed_step) + 1])
            session.rollback.assert_called_once()
            warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
            assert any("Failed to clean up bindings" in record.message and "idx-1" in record.message for record in warnings)
        else:
            assert events == expected
            session.commit.assert_called_once()
            session.rollback.assert_not_called()
