# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Legacy database facade forwards resolved outlet operations unchanged."""

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest
from test.backend.database.model_outlet_helpers import database, load


@pytest.mark.parametrize(
    "name",
    [
        "create_resolved_model_record",
        "get_resolved_model_record",
        "update_resolved_model_record",
    ],
)
def test_model_management_entry_delegates_without_legacy_filter(
    database, monkeypatch, name
):
    db, client, _ = database
    constants = ModuleType("consts.const")
    constants.DEFAULT_EXPECTED_CHUNK_SIZE = 1024
    constants.DEFAULT_MAXIMUM_CHUNK_SIZE = 1536
    monkeypatch.setitem(sys.modules, "consts.const", constants)
    model_constants = ModuleType("consts.model")
    model_constants.filter_extra_params = MagicMock(
        side_effect=AssertionError("New profile must not enter legacy filter")
    )
    monkeypatch.setitem(sys.modules, "consts.model", model_constants)
    client.as_dict, client.db_client = MagicMock(), MagicMock()
    delegated = MagicMock(return_value=42)
    monkeypatch.setattr(db, name, delegated)
    facade = load(
        "_outlet_unit_db.model_management_db",
        "backend/database/model_management_db.py",
        monkeypatch,
    )
    assert getattr(facade, name)("profile-or-id", tenant_id="tenant-one") == 42
    delegated.assert_called_once_with("profile-or-id", tenant_id="tenant-one")
    model_constants.filter_extra_params.assert_not_called()

