# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""All existing LLM writes reach resolved storage; other model types stay unchanged."""

import sys
from types import ModuleType
from unittest.mock import Mock

import pytest

from test.backend.services.test_model_management_service import import_svc


@pytest.fixture
def writers(monkeypatch):
    service = import_svc(isolate_storage=False)
    legacy = ModuleType("management.services.model.outlet_legacy")
    legacy.create_legacy_llm_outlet = Mock(return_value=42)
    legacy.update_legacy_llm_outlet = Mock(return_value=2)
    monkeypatch.setitem(sys.modules, legacy.__name__, legacy)
    monkeypatch.setattr(service, "create_model_record", Mock(return_value=43))
    monkeypatch.setattr(service, "update_model_record", Mock(return_value=True))
    return service, legacy


@pytest.mark.parametrize("kind", ["llm", "chat"])
def test_llm_writers_use_one_resolved_storage_path(writers, kind):
    service, legacy = writers
    row = {"model_id": 42, "model_type": kind}
    assert service._create_model_configuration(row, "user", "tenant") == 42
    legacy.create_legacy_llm_outlet.assert_called_once_with(row, "user", "tenant")
    assert service._update_model_configuration(row, {"temperature": 0}, "user", "tenant") == 2
    legacy.update_legacy_llm_outlet.assert_called_once_with(row, {"temperature": 0}, "user", "tenant")
    service.create_model_record.assert_not_called()
    service.update_model_record.assert_not_called()


@pytest.mark.parametrize("kind", ["vlm", "embedding", "rerank", "stt", "tts"])
@pytest.mark.parametrize("scoped", [False, True])
def test_non_llm_writers_keep_existing_storage_contract(writers, kind, scoped):
    service, legacy = writers
    row = {"model_id": 43, "model_type": kind}
    assert service._create_model_configuration(row, "user", "tenant") == 43
    service.create_model_record.assert_called_once_with(row, "user", "tenant")
    assert service._update_model_configuration(row, {"display_name": "same"}, "user", "tenant", scope_update=scoped)
    args = (43, {"display_name": "same"}, "user") + (("tenant",) if scoped else ())
    service.update_model_record.assert_called_once_with(*args)
    legacy.create_legacy_llm_outlet.assert_not_called()
    legacy.update_legacy_llm_outlet.assert_not_called()


def test_missing_record_does_not_write(writers):
    service, legacy = writers
    with pytest.raises(LookupError, match="MODEL_OUTLET_NOT_FOUND"):
        service._update_model_configuration(None, {}, "user", "tenant")
    service.update_model_record.assert_not_called()
    legacy.update_legacy_llm_outlet.assert_not_called()
