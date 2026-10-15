# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Batch cleanup, provider isolation, transaction and deletion entry contracts."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import database.client as db_client
import database.knowledge_reference_db as reference_db
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
    monkeypatch.setattr(reference_db, "as_dict", vars)
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
    counts = reference_db.strip_deleted_resource_from_bindings(session, [
        ("local", "idx-1"), ("local", "idx-2"), ("aidp", "213"), ("local", "idx-1"),
    ])
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
    assert reference_db.strip_deleted_resource_from_bindings(session, []) == {
        "tool_instances": 0, "skill_instances": 0, "conversations": 0,
    }
    assert reference_db.query_reference_rows(session, []) == []
    session.query.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("delete_fails,cleanup_fails", [(False, False), (True, False), (False, True)])
async def test_local_delete_cascades_only_after_success_and_owns_transaction(monkeypatch, delete_fails, cleanup_fails):
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

    def clean(db_session, resources):
        assert db_session is session
        assert resources == [("local", "idx-1")]
        events.append("cleaned")
        if cleanup_fails:
            raise RuntimeError("cleanup failed")
        return {"tool_instances": 1}

    monkeypatch.setattr(cls, "delete_index", staticmethod(delete_index))
    cleanup = MagicMock(side_effect=clean)
    monkeypatch.setattr(local_management, "strip_deleted_resource_from_bindings", cleanup)
    if delete_fails or cleanup_fails:
        with pytest.raises(RuntimeError, match="ES failed" if delete_fails else "cleanup failed"):
            await cls.full_delete_knowledge_base("idx-1", MagicMock(), "u1")
        session.commit.assert_not_called()
        if delete_fails:
            cleanup.assert_not_called()
            session.rollback.assert_not_called()
        else:
            session.rollback.assert_called_once()
    else:
        result = await cls.full_delete_knowledge_base("idx-1", MagicMock(), "u1")
        assert result["status"] == "success"
        session.commit.assert_called_once()
        session.rollback.assert_not_called()
    assert events == (["deleted"] if delete_fails else ["deleted", "cleaned"])


@pytest.mark.parametrize("status", [204, 404, 403, 500])
def test_aidp_delete_cascades_only_on_success_or_already_absent(monkeypatch, status):
    events = []
    session = MagicMock()
    monkeypatch.setattr(db_client.db_client, "session_maker", lambda: session)
    monkeypatch.setattr(aidp_service, "get_db_session", db_client.get_db_session)
    response = httpx.Response(status, request=httpx.Request("DELETE", "http://aidp.test/kb/kds-1"))

    def remote_delete(*args, **kwargs):
        events.append("deleted")
        return response

    manager = MagicMock()
    manager.get_sync_client.return_value.delete.side_effect = remote_delete
    monkeypatch.setattr(aidp_service, "http_client_manager", manager)

    def clean(db_session, resources):
        assert db_session is session
        assert resources == [("aidp", "kds-1")]
        events.append("cleaned")

    cleanup = MagicMock(side_effect=clean)
    monkeypatch.setattr(aidp_service, "strip_deleted_resource_from_bindings", cleanup)
    if status in (204, 404):
        assert aidp_service.delete_aidp_kb_impl("http://aidp.test", "test-key", "kds-1") is True
        assert events == ["deleted", "cleaned"]
        session.commit.assert_called_once()
    else:
        with pytest.raises(aidp_service.AppException):
            aidp_service.delete_aidp_kb_impl("http://aidp.test", "test-key", "kds-1")
        cleanup.assert_not_called()
        session.commit.assert_not_called()
        assert events == ["deleted"]


def test_aidp_cleanup_failure_rolls_back_and_propagates(monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(db_client.db_client, "session_maker", lambda: session)
    monkeypatch.setattr(aidp_service, "get_db_session", db_client.get_db_session)
    monkeypatch.setattr(aidp_service, "http_client_manager", MagicMock())
    monkeypatch.setattr(aidp_service, "strip_deleted_resource_from_bindings", MagicMock(
        side_effect=RuntimeError("cleanup failed"),
    ))
    with pytest.raises(RuntimeError, match="cleanup failed"):
        aidp_service.delete_aidp_kb_impl("http://aidp.test", "test-key", "kds-1")
    session.rollback.assert_called_once()
    session.commit.assert_not_called()
