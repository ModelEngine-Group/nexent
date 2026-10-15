# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Batch cleanup, provider isolation, transaction and deletion entry contracts."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import database.agent_db as agent_db
import database.client as db_client
import database.conversation_db as conversation_db
import database.skill_db as skill_db
import database.tool_db as tool_db
import ext_components.aidp.services.aidp_service as aidp_service
import management.services.knowledge_base.management as local_management


def _session(*results):
    session = MagicMock()
    queries = []
    for rows in results:
        query = MagicMock()
        query.filter.return_value = query
        query.all.return_value = rows
        queries.append(query)
    session.query.side_effect = queries
    return session


def test_batch_cleanup_keeps_providers_separate_and_updates_each_row_once(monkeypatch):
    monkeypatch.setattr(tool_db, "as_dict", vars)
    monkeypatch.setattr(skill_db, "as_dict", vars)
    local_tool = SimpleNamespace(params={
        "index_names": ["idx-1", "idx-2", "keep"], "display_names": ["A", "B", "C"],
    })
    aidp_tool = SimpleNamespace(params={
        "kds_list": '["213", "idx-1", "keep"]', "display_names": ["X", "Y", "Z"],
    })
    skill = SimpleNamespace(config_values={
        "index_names": ["idx-1", "idx-2", "keep"], "kds_list": ["213", "idx-1"], "other": 1,
    })
    scope = {
        "local": {"mode": "override", "knowledge_ids": [213, 214, 999]},
        "aidp": {"mode": "override", "kds_ids": ["213", "idx-1"]},
    }
    conversation = SimpleNamespace(
        knowledge_scope=deepcopy(scope),
        workbench_config={"knowledge_scope": deepcopy(scope), "other": "keep"},
    )
    session = _session(
        [(63,)], [local_tool], [(64,)], [aidp_tool], [skill],
        [SimpleNamespace(knowledge_id=213), SimpleNamespace(knowledge_id=214)], [conversation],
    )
    selected = {"index_names": ["idx-1", "idx-2", "idx-1"], "kds_ids": ["213"]}
    counts = {
        "tool_instances": tool_db.remove_tool_knowledge_bindings(session, **selected),
        "skill_instances": skill_db.remove_skill_knowledge_bindings(session, **selected),
        "conversations": conversation_db.remove_conversation_knowledge_bindings(session, **selected),
    }
    assert counts == {"tool_instances": 2, "skill_instances": 1, "conversations": 1}
    assert local_tool.params == {"index_names": ["keep"], "display_names": ["C"]}
    assert aidp_tool.params == {"kds_list": '["idx-1", "keep"]', "display_names": ["Y", "Z"]}
    assert skill.config_values == {"index_names": ["keep"], "kds_list": ["idx-1"], "other": 1}
    expected = {
        "local": {"mode": "override", "knowledge_ids": [999]},
        "aidp": {"mode": "override", "kds_ids": ["idx-1"]},
    }
    assert conversation.knowledge_scope == expected
    assert conversation.workbench_config == {"knowledge_scope": expected, "other": "keep"}
    assert scope["local"]["knowledge_ids"] == [213, 214, 999]
    assert session.query.call_count == 7
    session.commit.assert_not_called()


def test_empty_cleanup_batch_does_not_query_database():
    session = _session()
    assert tool_db.remove_tool_knowledge_bindings(session) == 0
    assert skill_db.remove_skill_knowledge_bindings(session) == 0
    assert conversation_db.remove_conversation_knowledge_bindings(session) == 0
    assert agent_db.query_live_knowledge_bindings(session) == []
    session.query.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("delete_fails,failed_step", [
    (False, None), (True, None), (False, "tool"), (False, "skill"), (False, "conversation"),
])
async def test_local_delete_owns_one_transaction_for_all_bindings(monkeypatch, delete_fails, failed_step):
    cls = local_management.KnowledgeBaseManagementService
    events = []
    session = MagicMock()
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
            return 1
        return run

    monkeypatch.setattr(cls, "delete_index", staticmethod(delete_index))
    for step in ("tool", "skill", "conversation"):
        monkeypatch.setattr(local_management, f"remove_{step}_knowledge_bindings", clean(step))
    if delete_fails or failed_step:
        with pytest.raises(RuntimeError, match="ES failed" if delete_fails else "cleanup failed"):
            await cls.full_delete_knowledge_base("idx-1", MagicMock(), "u1")
        session.commit.assert_not_called()
        if delete_fails:
            assert events == ["deleted"]
            session.rollback.assert_not_called()
        else:
            expected = ["deleted", "tool", "skill", "conversation"]
            assert events == expected[:expected.index(failed_step) + 1]
            session.rollback.assert_called_once()
    else:
        result = await cls.full_delete_knowledge_base("idx-1", MagicMock(), "u1")
        assert result["status"] == "success"
        assert events == ["deleted", "tool", "skill", "conversation"]
        session.commit.assert_called_once()
        session.rollback.assert_not_called()


@pytest.mark.parametrize("status", [204, 404, 403, 500])
def test_aidp_delete_only_cleans_on_success_or_already_absent(monkeypatch, status):
    events = []
    session = MagicMock()
    monkeypatch.setattr(db_client.db_client, "session_maker", lambda: session)
    monkeypatch.setattr(aidp_service, "get_db_session", db_client.get_db_session)
    response = httpx.Response(status, request=httpx.Request("DELETE", "http://aidp.test/kb/kds-1"))
    manager = MagicMock()
    manager.get_sync_client.return_value.delete.side_effect = lambda *args, **kwargs: events.append("deleted") or response
    monkeypatch.setattr(aidp_service, "http_client_manager", manager)

    def clean(step):
        def run(db_session, *, kds_ids):
            assert db_session is session
            assert kds_ids == ["kds-1"]
            events.append(step)
        return run

    for step in ("tool", "skill", "conversation"):
        monkeypatch.setattr(aidp_service, f"remove_{step}_knowledge_bindings", clean(step))
    if status in (204, 404):
        assert aidp_service.delete_aidp_kb_impl("http://aidp.test", "test-key", "kds-1") is True
        assert events == ["deleted", "tool", "skill", "conversation"]
        session.commit.assert_called_once()
    else:
        with pytest.raises(aidp_service.AppException):
            aidp_service.delete_aidp_kb_impl("http://aidp.test", "test-key", "kds-1")
        assert events == ["deleted"]
        session.commit.assert_not_called()


@pytest.mark.parametrize("failed_step", ["tool", "skill", "conversation"])
def test_aidp_binding_failure_rolls_back_all_updates(monkeypatch, failed_step):
    session = MagicMock()
    monkeypatch.setattr(db_client.db_client, "session_maker", lambda: session)
    monkeypatch.setattr(aidp_service, "get_db_session", db_client.get_db_session)
    monkeypatch.setattr(aidp_service, "http_client_manager", MagicMock())
    for step in ("tool", "skill", "conversation"):
        cleanup = MagicMock(side_effect=RuntimeError("cleanup failed") if step == failed_step else None)
        monkeypatch.setattr(aidp_service, f"remove_{step}_knowledge_bindings", cleanup)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        aidp_service.delete_aidp_kb_impl("http://aidp.test", "test-key", "kds-1")
    session.rollback.assert_called_once()
    session.commit.assert_not_called()
