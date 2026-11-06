# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Sampling display metadata and runtime inheritance retain stored intent."""

from copy import deepcopy

import pytest
from management.services.model.run_bindings import create_model_config_from_record
from management.services.model import management


@pytest.mark.parametrize("sampling,expected", [
    ({}, {"temperature": 1.0, "top_p": 1.0}),
    ({"temperature": None, "top_p": None}, {"temperature": 1.0, "top_p": 1.0}),
    ({"temperature": 0, "top_p": None}, {"temperature": 0, "top_p": 1.0}),
    ({"temperature": 0.3, "top_p": 0.87}, {"temperature": 0.3, "top_p": 0.87}),
])
async def test_model_list_exposes_effective_sampling_without_filling_stored_fields(monkeypatch, sampling, expected):
    record = {"model_id": 1, "model_repo": "", "model_name": "fixture", "display_name": "Fixture",
              "model_type": "llm", "base_url": "http://fixture.invalid", "connect_status": "available", **sampling}
    original = deepcopy(record)
    monkeypatch.setattr(management, "get_model_records", lambda *args: [deepcopy(record)])
    monkeypatch.setattr(management, "_enrich_model_reasoning_capability", lambda row: None)
    result = (await management.list_models_for_tenant("fixture-tenant"))[0]
    assert result["effective_sampling"] == expected
    for key in ("temperature", "top_p"):
        assert result.get(key) == original.get(key)
        assert (key in result) == (key in original)
    from contracts.errors.exceptions import ModelOutletValidationError

    # Persisted LLM rows must be migrated before runtime use. Anonymous legacy
    # bindings still preserve the upstream sampling inheritance contract.
    with pytest.raises(ModelOutletValidationError) as error:
        create_model_config_from_record(record)
    assert error.value.category == "PROFILE_MIGRATION_REQUIRED"
    anonymous = {key: value for key, value in record.items() if key != "model_id"}
    base = create_model_config_from_record(anonymous)
    inherited = base
    assert {key: getattr(inherited, key) for key in expected} == expected
    assert inherited.explicit_sampling == []
    assert record == original


async def test_sampling_metadata_is_not_added_to_non_generation_models(monkeypatch):
    record = {"model_id": 2, "model_repo": "", "model_name": "fixture-embedding",
              "model_type": "embedding", "connect_status": "available"}
    monkeypatch.setattr(management, "get_model_records", lambda *args: [record])
    monkeypatch.setattr(management, "_enrich_model_reasoning_capability", lambda row: None)
    assert "effective_sampling" not in (await management.list_models_for_tenant("fixture-tenant"))[0]
