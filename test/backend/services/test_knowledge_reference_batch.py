# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Batch cleanup, provider isolation, transaction and deletion entry contracts."""

from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import database.client as db_client
import database.knowledge_reference_db as reference_db
import ext_components.aidp.apps.aidp_mgmt_app as aidp_app
import management.services.knowledge_base.management as local_management
import services.knowledge_reference_service as service


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


@pytest.mark.parametrize("fails", [False, True])
def test_cleanup_transaction_is_owned_by_session_context(monkeypatch, fails):
    session = MagicMock()
    monkeypatch.setattr(db_client.db_client, "session_maker", lambda: session)
    monkeypatch.setattr(service, "get_db_session", db_client.get_db_session)
    cleanup = MagicMock(return_value={"tool_instances": 2})
    if fails:
        cleanup.side_effect = RuntimeError("update failed")
    monkeypatch.setattr(service, "strip_deleted_resource_from_bindings", cleanup)
    resources = [("local", "idx-1"), ("aidp", "kds-1")]
    if fails:
        with pytest.raises(RuntimeError, match="update failed"):
            service.remove_knowledge_references(resources)
        session.rollback.assert_called_once()
        session.commit.assert_not_called()
    else:
        assert service.remove_knowledge_references(resources) == {"tool_instances": 2}
        session.commit.assert_called_once()
        session.rollback.assert_not_called()
    cleanup.assert_called_once_with(session, resources)
    session.close.assert_called_once()


def test_delete_and_write_batches_share_lock_keys(monkeypatch):
    held = []

    @contextmanager
    def locks(keys):
        held.append(set(keys))
        yield

    monkeypatch.setattr(service, "acquire_lock_keys", locks)
    resources = [("local", "213"), ("aidp", "213")]
    with service.knowledge_deletion_guard(resources):
        pass
    with service.knowledge_reference_write_guard(list(reversed(resources))):
        pass
    assert held[0] == held[1]
    assert len(held[0]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_local_delete_passes_a_single_element_batch_after_index_deletion(monkeypatch, fails):
    events = []

    @contextmanager
    def guard(resources):
        assert resources == [("local", "idx-1")]
        events.append("locked")
        try:
            yield
        finally:
            events.append("released")

    async def delete_index(*args):
        events.append("deleted")
        if fails:
            raise RuntimeError("es unavailable")
        return {"success": True}

    monkeypatch.setattr(local_management, "knowledge_deletion_guard", guard)
    cleanup = MagicMock(side_effect=lambda resources: events.append("cleaned"))
    monkeypatch.setattr(local_management, "remove_knowledge_references", cleanup)
    cls = local_management.KnowledgeBaseManagementService
    monkeypatch.setattr(cls, "_full_delete_knowledge_base_locked", staticmethod(delete_index))
    if fails:
        with pytest.raises(RuntimeError, match="es unavailable"):
            await cls.full_delete_knowledge_base("idx-1", MagicMock(), "u1")
        cleanup.assert_not_called()
        assert events == ["locked", "deleted", "released"]
    else:
        assert await cls.full_delete_knowledge_base("idx-1", MagicMock(), "u1") == {"success": True}
        cleanup.assert_called_once_with([("local", "idx-1")])
        assert events == ["locked", "deleted", "cleaned", "released"]


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [False, True])
async def test_aidp_delete_only_cleans_a_single_element_batch_after_upstream_success(monkeypatch, success):
    events = []

    @contextmanager
    def guard(resources):
        assert resources == [("aidp", "kds-1")]
        events.append("locked")
        yield
        events.append("released")

    monkeypatch.setattr(aidp_app, "_auth", AsyncMock(return_value=("u1", "t1")))
    monkeypatch.setattr(aidp_app, "_credentials", lambda: ("http://aidp.test", "test-key"))
    monkeypatch.setattr(aidp_app, "perms", MagicMock())
    monkeypatch.setattr(aidp_app, "knowledge_deletion_guard", guard)
    upstream = MagicMock(side_effect=lambda *args: events.append("deleted") or success)
    monkeypatch.setattr(aidp_app, "delete_aidp_kb_impl", upstream)
    for name in (
        "invalidate_aidp_catalog_cache", "invalidate_aidp_kb_detail_cache", "invalidate_aidp_doc_count_cache",
        "_cleanup_document_assignments_for_deleted_knowledge_base",
    ):
        monkeypatch.setattr(aidp_app, name, MagicMock())
    cleanup = MagicMock(side_effect=lambda resources: events.append("cleaned"))
    monkeypatch.setattr(aidp_app, "remove_knowledge_references", cleanup)
    response = await aidp_app.delete_knowledge_base(MagicMock(), "kds-1")
    assert response.status_code == 200
    upstream.assert_called_once_with("http://aidp.test", "test-key", "kds-1")
    if success:
        cleanup.assert_called_once_with([("aidp", "kds-1")])
        assert events == ["locked", "deleted", "cleaned", "released"]
    else:
        cleanup.assert_not_called()
        aidp_app.perms.soft_delete_permission.assert_not_called()
        assert events == ["locked", "deleted", "released"]
