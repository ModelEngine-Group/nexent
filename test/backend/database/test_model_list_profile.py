# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Batch list reads retain the resolved profile contract without credentials."""

from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from nexent.core.model_service.profiles.outlet_storage import (
    decode_resolved_model_profile,
)

from test.backend.database import model_outlet_helpers as helpers

database = helpers.database
profile = helpers.profile


@pytest.fixture
def repository(database, monkeypatch):
    _, client, _ = database
    client.db_client = MagicMock()
    return helpers.load("management.db.model._list_profile_unit", "backend/management/db/model/repository.py", monkeypatch)


def test_batch_rows_decode_with_all_saved_profile_fields(repository, profile, monkeypatch):
    stored = {**helpers.row(profile), "delete_flag": "N", "api_key": "private", "http_headers": {"secret": "private"}}
    original = deepcopy(stored)
    session = MagicMock()

    def execute(statement):
        columns = {column.key for column in statement.selected_columns}
        assert "api_key" not in columns
        assert "http_headers" not in columns
        result = MagicMock()
        result.mappings.return_value.all.return_value = [{key: stored.get(key) for key in columns}]
        return result

    session.execute.side_effect = execute

    @contextmanager
    def get_session():
        yield session

    monkeypatch.setattr(repository, "get_db_session", get_session)
    records = repository.get_model_records_by_ids([12, 999])
    assert set(records) == {12}
    assert records[12]["delete_flag"] == "N"
    restored = decode_resolved_model_profile(records[12], registered_references=helpers.REGISTRY)
    assert restored == profile
    assert stored == original
    session.execute.assert_called_once()
    assert session.execute.call_args.args[0].compile().params == {"model_id_1": [12, 999]}


def test_empty_ids_do_not_open_session(repository, mocker):
    session = mocker.patch.object(repository, "get_db_session")
    assert repository.get_model_records_by_ids([]) == {}
    session.assert_not_called()


@pytest.mark.parametrize("rows", [[], [{"model_id": 21, "delete_flag": "Y", "tenant_id": "other", "profile_schema_version": None}]])
def test_batch_retains_missing_deleted_and_legacy_semantics(repository, monkeypatch, rows):
    session = MagicMock()
    session.execute.return_value.mappings.return_value.all.return_value = rows

    @contextmanager
    def get_session():
        yield session

    monkeypatch.setattr(repository, "get_db_session", get_session)
    assert repository.get_model_records_by_ids([21]) == {r["model_id"]: r for r in rows}


def test_query_failure_remains_visible(repository, monkeypatch):
    @contextmanager
    def get_session():
        raise RuntimeError("database unavailable")
        yield

    monkeypatch.setattr(repository, "get_db_session", get_session)
    with pytest.raises(RuntimeError, match="database unavailable"):
        repository.get_model_records_by_ids([12])
