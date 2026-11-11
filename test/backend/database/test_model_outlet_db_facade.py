# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Legacy database facade forwards resolved outlet operations unchanged."""

import sys
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
    from contracts import model as model_contract
    legacy_filter = MagicMock(
        side_effect=AssertionError("New profile must not enter legacy filter")
    )
    monkeypatch.setattr(model_contract, "filter_extra_params", legacy_filter)
    client.as_dict, client.db_client = MagicMock(), MagicMock()
    delegated = MagicMock(return_value=42)
    monkeypatch.setattr(db, name, delegated)
    monkeypatch.setitem(sys.modules, "management.db.model.outlets", db)
    facade = load(
        "management.db.model._outlet_facade_unit",
        "backend/management/db/model/repository.py",
        monkeypatch,
    )
    assert getattr(facade, name)("profile-or-id", tenant_id="tenant-one") == 42
    delegated.assert_called_once_with("profile-or-id", tenant_id="tenant-one")
    legacy_filter.assert_not_called()

