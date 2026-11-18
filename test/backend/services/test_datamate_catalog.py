# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""DataMate catalog policy must preserve quotas, ownership, CAS and tenant scope."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from contracts.errors.exceptions import AppException, DuplicateError
from management.services.knowledge_base.providers import catalog
from nexent.storage.errors import Conflict, OutcomeUnknown, ScopeDenied
from nexent.storage.models import WriteOutcome


@pytest.fixture
def boundary():
    records = MagicMock()
    records.transaction.return_value.__enter__.return_value = records
    records.query.side_effect = [
        SimpleNamespace(items=()),
        SimpleNamespace(items=({"user_roles": ["USER"]},)),
    ]
    records.count.side_effect = [0, 0, 0]
    records.create.return_value = {
        "knowledge_id": 7,
        "index_name": "remote",
        "knowledge_name": "KB",
    }
    calls = []

    @contextmanager
    def ports(actor, *, context, writable=False, knowledge_name=None):
        calls.append((actor.user_id, actor.tenant_id, writable, knowledge_name))
        yield records

    return records, ports, calls


def request():
    return {
        "index_name": "remote",
        "tenant_id": "tenant-a",
        "user_id": "admin",
        "knowledge_name": "KB",
        "knowledge_describe": "description",
        "embedding_model_name": "external-embedding",
    }


def existing(**values):
    return {
        "knowledge_id": 7,
        "index_name": "remote",
        "knowledge_sources": "datamate",
        "deletion_request": None,
        "knowledge_name": "old",
        "version": 4,
        "created_by": "creator",
        "group_ids": "[9]",
        **values,
    }


def test_create_uses_actual_actor_and_preserves_response(boundary):
    records, ports, calls = boundary
    assert catalog.upsert_datamate_record(request(), ports=ports) == {
        "knowledge_id": 7,
        "index_name": "remote",
        "knowledge_name": "KB",
    }
    assert calls == [("admin", "tenant-a", True, "KB")]
    records.transaction.assert_called_once()
    values = records.create.call_args.args[1]
    assert (
        values["knowledge_sources"] == "datamate"
        and values["preserve_source_file"] is True
    )
    assert not {"created_by", "updated_by", "version"}.intersection(values)


def test_update_uses_cas_without_overwriting_creator_or_permissions(boundary):
    records, ports, _ = boundary
    records.query.side_effect = None
    records.query.return_value = SimpleNamespace(items=(existing(),))
    records.patch.return_value = SimpleNamespace(
        outcome=WriteOutcome.CONFIRMED, matched=True
    )
    assert (
        catalog.upsert_datamate_record(request(), ports=ports)["knowledge_name"] == "KB"
    )
    patch = records.patch.call_args.args[2]
    assert not {
        "created_by",
        "group_ids",
        "ingroup_permission",
        "tenant_id",
    }.intersection(patch.set_values)
    assert records.patch.call_args.kwargs["expected"].value == "4"
    records.count.assert_not_called()
    records.create.assert_not_called()


@pytest.mark.parametrize(
    "row",
    [
        existing(knowledge_sources="elasticsearch"),
        existing(deletion_request={"active": True}),
    ],
)
def test_existing_local_or_deleting_resources_are_not_overwritten(boundary, row):
    records, ports, _ = boundary
    records.query.side_effect = None
    records.query.return_value = SimpleNamespace(items=(row,))
    with pytest.raises(ScopeDenied):
        catalog.upsert_datamate_record(request(), ports=ports)
    records.patch.assert_not_called()
    records.create.assert_not_called()


@pytest.mark.parametrize("counts,scope", [([3], "tenant"), ([0, 2], "user")])
def test_original_quotas_prevent_insert(boundary, monkeypatch, counts, scope):
    records, ports, _ = boundary
    monkeypatch.setattr(catalog, "MAX_KNOWLEDGE_BASES_PER_TENANT", 3)
    monkeypatch.setattr(catalog, "MAX_KNOWLEDGE_BASES_PER_USER", 2)
    records.count.side_effect = counts
    with pytest.raises(AppException) as error:
        catalog.upsert_datamate_record(request(), ports=ports)
    assert error.value.details["scope"] == scope
    records.create.assert_not_called()


def test_privileged_role_keeps_original_higher_limit(boundary, monkeypatch):
    records, ports, _ = boundary
    monkeypatch.setattr(catalog, "MAX_KNOWLEDGE_BASES_PER_USER", 1)
    monkeypatch.setattr(catalog, "MAX_PRIVILEGED_KNOWLEDGE_BASES_PER_USER", 3)
    records.query.side_effect = [
        SimpleNamespace(items=()),
        SimpleNamespace(items=({"user_roles": ["DEV"]},)),
    ]
    records.count.side_effect = [0, 2, 0]
    catalog.upsert_datamate_record(request(), ports=ports)
    records.create.assert_called_once()


def test_duplicate_name_prevents_insert(boundary):
    records, ports, _ = boundary
    records.count.side_effect = [0, 0, 1]
    with pytest.raises(DuplicateError):
        catalog.upsert_datamate_record(request(), ports=ports)
    records.create.assert_not_called()


@pytest.mark.parametrize(
    "outcome,matched,error",
    [
        (WriteOutcome.UNKNOWN, False, OutcomeUnknown),
        (WriteOutcome.CONFIRMED, False, Conflict),
    ],
)
def test_unknown_or_racing_update_is_not_replayed(boundary, outcome, matched, error):
    records, ports, _ = boundary
    records.query.side_effect = None
    records.query.return_value = SimpleNamespace(items=(existing(),))
    records.patch.return_value = SimpleNamespace(outcome=outcome, matched=matched)
    with pytest.raises(error):
        catalog.upsert_datamate_record(request(), ports=ports)
    assert records.patch.call_count == 1


def test_delete_is_scoped_to_actual_tenant_and_source(boundary):
    records, ports, calls = boundary
    records.query.side_effect = None
    records.query.return_value = SimpleNamespace(items=(existing(),))
    records.delete.return_value = SimpleNamespace(
        outcome=WriteOutcome.CONFIRMED, deleted=True
    )
    assert catalog.delete_datamate_record(
        {"index_name": "remote", "user_id": "admin", "tenant_id": "tenant-a"},
        ports=ports,
    )
    assert calls == [("admin", "tenant-a", True, None)]
    assert records.delete.call_args.kwargs["expected"].value == "4"


def test_missing_delete_does_not_write(boundary):
    records, ports, _ = boundary
    records.query.side_effect = None
    records.query.return_value = SimpleNamespace(items=())
    assert not catalog.delete_datamate_record(
        {"index_name": "remote", "user_id": "admin", "tenant_id": "tenant-a"},
        ports=ports,
    )
    records.delete.assert_not_called()


@pytest.mark.parametrize(
    "row",
    [
        existing(knowledge_sources="elasticsearch"),
        existing(deletion_request={"active": True}),
    ],
)
def test_delete_rejects_local_or_pending_resources(boundary, row):
    records, ports, _ = boundary
    records.query.side_effect = None
    records.query.return_value = SimpleNamespace(items=(row,))
    with pytest.raises(ScopeDenied):
        catalog.delete_datamate_record(request(), ports=ports)
    records.delete.assert_not_called()


def test_create_failure_closes_transaction_without_retry(boundary):
    records, ports, _ = boundary
    records.create.side_effect = OutcomeUnknown()
    with pytest.raises(OutcomeUnknown):
        catalog.upsert_datamate_record(request(), ports=ports)
    assert records.create.call_count == 1
    records.transaction.return_value.__exit__.assert_called_once()


def test_list_filters_datamate_and_follows_only_forward_pages(boundary):
    records, ports, calls = boundary
    records.query.side_effect = [
        SimpleNamespace(items=({"index_name": "one"},), next_cursor="page-two"),
        SimpleNamespace(items=({"index_name": "two"},), next_cursor=None),
    ]
    assert catalog.list_datamate_records("tenant-a", "reader", ports=ports) == [
        {"index_name": "one"},
        {"index_name": "two"},
    ]
    assert calls == [("reader", "tenant-a", False, None)]
    first, second = records.query.call_args_list
    assert (
        first.args[1].where.value == "datamate"
        and first.args[1].where.field == "knowledge_sources"
    )
    assert first.args[2].cursor is None and second.args[2].cursor == "page-two"


def test_list_empty_is_not_an_error(boundary):
    records, ports, _ = boundary
    records.query.side_effect = None
    records.query.return_value = SimpleNamespace(items=(), next_cursor=None)
    assert catalog.list_datamate_records("tenant-a", "reader", ports=ports) == []
