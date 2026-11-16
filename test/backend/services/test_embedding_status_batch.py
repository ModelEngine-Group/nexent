# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Embedding status retains configured/index semantics with targeted reads."""

import pytest

from management.db.configuration import tenant
from management.services.configuration.tenant import settings
from management.services.memory import records


@pytest.mark.parametrize("value", [None, "", "invalid", "1"])
def test_status_reuses_record_and_targeted_model_configuration(mocker, value):
    first = mocker.patch.object(tenant, "get_single_config_info", return_value={"config_value": value})
    selected = mocker.patch.object(settings, "get_configs_by_tenant_id_and_keys", return_value={"EMBEDDING_ID": value})
    full = mocker.patch.object(settings, "get_all_configs_by_tenant_id", side_effect=AssertionError("Full config scan"))
    model = mocker.patch.object(settings, "get_model_by_model_id", return_value={
        "model_name": "embedding", "model_repo": "repo", "base_url": "http://model.invalid",
        "max_tokens": 1024,
    })
    result = records.get_tenant_embedding_status("a")
    first.assert_called_once_with("a", "EMBEDDING_ID")
    full.assert_not_called()
    assert result["configured"] is bool(value)
    if value == "1":
        model.assert_called_once_with(model_id=1, tenant_id="a")
        assert result["current_es_index_name"] is not None
    else:
        assert result["current_es_index_name"] is None
        model.assert_not_called()
    assert selected.call_count == (1 if value else 0)


def test_model_resolution_failure_keeps_configured_flag(mocker):
    mocker.patch.object(tenant, "get_single_config_info", return_value={"config_value": "1"})
    mocker.patch.object(settings, "get_configs_by_tenant_id_and_keys", side_effect=RuntimeError("database down"))
    assert records.get_tenant_embedding_status("a") == {"configured": True, "current_es_index_name": None}


def test_initial_configuration_error_is_not_silently_accepted(mocker):
    mocker.patch.object(tenant, "get_single_config_info", side_effect=RuntimeError("database down"))
    with pytest.raises(RuntimeError, match="database down"):
        records.get_tenant_embedding_status("a")
