# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Tool writes must persist canonical index names, never numeric KB aliases."""

from contextlib import contextmanager

import pytest

import management.services.knowledge_base.permission as permissions
import services.knowledge_reference_service as service


INDEX_NAME = "213-a99a7c1e4da34a2aa98d41e8abd7802c"


@pytest.fixture(autouse=True)
def dependencies(monkeypatch):
    @contextmanager
    def session():
        yield object()

    monkeypatch.setattr(service, "get_db_session", session)
    monkeypatch.setattr(service, "query_local_knowledge_records", lambda session, names: {
        name: {"knowledge_id": 213, "index_name": INDEX_NAME}
        for name in names if name == INDEX_NAME
    })
    monkeypatch.setattr(permissions, "resolve_knowledge_base_permission", lambda *args: "EDIT")


def test_write_path_rejects_numeric_knowledge_id_alias():
    assert service.get_accessible_local_indices(["213"], user_id="u1", tenant_id="t1") == set()


def test_write_path_accepts_canonical_index_name():
    assert service.get_accessible_local_indices([INDEX_NAME], user_id="u1", tenant_id="t1") == {INDEX_NAME}


def test_inaccessible_index_is_not_returned(monkeypatch):
    monkeypatch.setattr(permissions, "resolve_knowledge_base_permission", lambda *args: None)
    assert service.get_accessible_local_indices([INDEX_NAME], user_id="u1", tenant_id="t1") == set()


@pytest.mark.parametrize("error", [ValueError("deleted"), RuntimeError("permission backend unavailable")])
def test_deleted_index_and_permission_service_failure_are_distinct(monkeypatch, error):
    def resolve(*args):
        raise error

    monkeypatch.setattr(permissions, "resolve_knowledge_base_permission", resolve)
    if isinstance(error, ValueError):
        assert service.get_accessible_local_indices([INDEX_NAME], user_id="u1", tenant_id="t1") == set()
    else:
        with pytest.raises(RuntimeError, match="permission backend unavailable"):
            service.get_accessible_local_indices([INDEX_NAME], user_id="u1", tenant_id="t1")


def test_empty_input_does_not_query_records(monkeypatch):
    def unexpected_query(*args):
        raise AssertionError("empty input must not query records")

    monkeypatch.setattr(service, "query_local_knowledge_records", unexpected_query)
    assert service.get_accessible_local_indices([], user_id="u1", tenant_id="t1") == set()
