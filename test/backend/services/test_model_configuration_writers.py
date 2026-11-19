# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""All existing LLM writes reach resolved storage; other model types stay unchanged."""

from unittest.mock import Mock

import pytest

from contracts.errors.exceptions import ModelOutletValidationError
from runtime.model import configuration as service


@pytest.fixture(autouse=True)
def writers(monkeypatch):
    monkeypatch.setattr(service, "create_legacy_llm_outlet", Mock(return_value=42))
    monkeypatch.setattr(service, "update_legacy_llm_outlet", Mock(return_value=2))
    monkeypatch.setattr(service, "create_model_record", Mock(return_value=43))
    monkeypatch.setattr(service, "update_model_record", Mock(return_value=True))
    monkeypatch.setattr(service, "get_model_by_model_id", Mock())


@pytest.mark.parametrize("kind", ["llm", "chat"])
def test_llm_writers_use_one_resolved_storage_path(kind):
    row = {"model_id": 42, "model_type": kind}
    service.get_model_by_model_id.return_value = row
    assert service.create_model_configuration(row, "user", "tenant") == 42
    service.create_legacy_llm_outlet.assert_called_once_with(row, "user", "tenant")
    assert service.update_model_configuration(42, {"temperature": 0}, "user", "tenant") == 2
    service.update_legacy_llm_outlet.assert_called_once_with(row, {"temperature": 0}, "user", "tenant")
    service.create_model_record.assert_not_called()
    service.update_model_record.assert_not_called()


@pytest.mark.parametrize("kind", ["vlm", "embedding", "rerank", "stt", "tts"])
@pytest.mark.parametrize("scoped", [False, True])
def test_non_llm_writers_keep_existing_storage_contract(kind, scoped):
    row = {"model_id": 43, "model_type": kind}
    service.get_model_by_model_id.return_value = row
    tenant_id = "tenant" if scoped else None
    assert service.create_model_configuration(row, "user", "tenant") == 43
    service.create_model_record.assert_called_once_with(row, "user", "tenant")
    assert service.update_model_configuration(43, {"display_name": "same"}, "user", tenant_id)
    service.get_model_by_model_id.assert_called_once_with(43, tenant_id=tenant_id)
    service.update_model_record.assert_called_once_with(43, {"display_name": "same"}, "user", tenant_id)
    service.create_legacy_llm_outlet.assert_not_called()
    service.update_legacy_llm_outlet.assert_not_called()


def test_missing_record_does_not_write():
    service.get_model_by_model_id.return_value = None
    with pytest.raises(LookupError, match="MODEL_OUTLET_NOT_FOUND"):
        service.update_model_configuration(43, {}, "user", "tenant")
    service.update_model_record.assert_not_called()
    service.update_legacy_llm_outlet.assert_not_called()


@pytest.mark.parametrize("invalid", [{"top_p": 0}, {"extra_params": {"__custom__": {"top_p": 0}}}])
def test_legacy_model_writers_reject_zero_top_p_before_persistence(invalid):
    row = {"model_id": 42, "model_type": "llm"}
    with pytest.raises(ModelOutletValidationError) as create_error:
        service.create_model_configuration({**row, **invalid}, "user", "tenant")
    with pytest.raises(ModelOutletValidationError) as update_error:
        service.update_model_configuration(42, invalid, "user", "tenant")
    assert create_error.value.path == update_error.value.path == "/top_p"
    service.create_legacy_llm_outlet.assert_not_called()
    service.update_legacy_llm_outlet.assert_not_called()
