# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Batch cleanup, provider isolation, transaction and deletion entry contracts."""

import logging
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import database.client as db_client
import database.conversation_db as conversation_db
import database.tool_db as tool_db
import ext_components.aidp.services.aidp_service as aidp_service
import management.services.knowledge_base.management as local_management


def _session(*results):
    session = MagicMock()
    queries = []
    for rows in results:
        query = MagicMock()
        query.join.return_value = query
        query.filter.return_value = query
        query.with_for_update.return_value = query
        query.all.return_value = rows
        queries.append(query)
    session.query.side_effect = queries
    return session


def test_batch_cleanup_keeps_providers_separate_and_updates_each_row_once(monkeypatch):
    monkeypatch.setattr(tool_db, "as_dict", vars)
    local_tool = SimpleNamespace(params={
        "index_names": ["idx-1", "idx-2", "keep"], "top_k": 5,
    })
    aidp_tool = SimpleNamespace(params={
        "kds_list": ["213", "idx-1", "keep"], "top_k": 7,
    })
    scope = {
        "local": {"mode": "override", "knowledge_ids": ["213", "214", "999"]},
        "aidp": {"mode": "override", "kds_ids": ["213", "idx-1"]},
    }
    conversation = SimpleNamespace(
        knowledge_scope=deepcopy(scope),
        workbench_config={"knowledge_scope": deepcopy(scope), "other": "keep"},
        workbench_config_version=4,
    )
    session = _session(
        [local_tool], [aidp_tool],
        [SimpleNamespace(knowledge_id=213), SimpleNamespace(knowledge_id=214)], [conversation],
    )
    selected = {"index_names": ["idx-1", "idx-2", "idx-1"], "kds_ids": ["213"]}
    tool_db.remove_tool_knowledge_references(session, **selected)
    assert conversation_db.remove_conversation_knowledge_bindings(session, **selected) is None
    assert local_tool.params == {"index_names": ["keep"], "top_k": 5}
    assert aidp_tool.params == {"kds_list": ["idx-1", "keep"], "top_k": 7}
    expected = {
        "local": {"mode": "override", "knowledge_ids": ["999"]},
        "aidp": {"mode": "override", "kds_ids": ["idx-1"]},
    }
    assert conversation.knowledge_scope == expected
    assert conversation.workbench_config == {"knowledge_scope": expected, "other": "keep"}
    assert conversation.workbench_config_version == 5
    assert scope["local"]["knowledge_ids"] == ["213", "214", "999"]
    assert session.query.call_count == 4
    session.commit.assert_not_called()


def test_empty_cleanup_batch_does_not_query_database():
    session = _session()
    assert tool_db.remove_tool_knowledge_references(session) is None
    assert conversation_db.remove_conversation_knowledge_bindings(session) is None
    session.query.assert_not_called()


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
            return 1
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
            assert len([record for record in caplog.records if record.levelno == logging.ERROR]) == 1
            assert len(warnings) == 1
            assert warnings[0].levelno == logging.WARNING
            assert "idx-1" in warnings[0].message
        else:
            assert events == expected
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

    for step in ("tool", "conversation"):
        monkeypatch.setattr(aidp_service, ("remove_tool_knowledge_references" if step == "tool" else f"remove_{step}_knowledge_bindings"), clean(step))
    if status in (204, 404):
        assert aidp_service.delete_aidp_kb_impl("http://aidp.test", "test-key", "kds-1") is True
        assert events == ["deleted", "tool", "conversation"]
        session.commit.assert_called_once()
    else:
        with pytest.raises(aidp_service.AppException):
            aidp_service.delete_aidp_kb_impl("http://aidp.test", "test-key", "kds-1")
        assert events == ["deleted"]
        session.commit.assert_not_called()


@pytest.mark.parametrize("failed_step", ["tool", "conversation", "commit"])
def test_aidp_binding_failure_warns_but_returns_success(monkeypatch, caplog, failed_step):
    session = MagicMock()
    if failed_step == "commit":
        session.commit.side_effect = RuntimeError("cleanup failed")
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(db_client.db_client, "session_maker", lambda: session)
    monkeypatch.setattr(aidp_service, "get_db_session", db_client.get_db_session)
    monkeypatch.setattr(aidp_service, "http_client_manager", MagicMock())
    for step in ("tool", "conversation"):
        cleanup = MagicMock(side_effect=RuntimeError("cleanup failed") if step == failed_step else None)
        monkeypatch.setattr(aidp_service, ("remove_tool_knowledge_references" if step == "tool" else f"remove_{step}_knowledge_bindings"), cleanup)
    assert aidp_service.delete_aidp_kb_impl("http://aidp.test", "test-key", "kds-1") is True
    session.rollback.assert_called_once()
    if failed_step != "commit":
        session.commit.assert_not_called()
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len([record for record in caplog.records if record.levelno == logging.ERROR]) == 1
    assert len(warnings) == 1
    assert warnings[0].levelno == logging.WARNING
    assert "kds-1" in warnings[0].message
