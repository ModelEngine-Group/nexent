# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Existing LLM checks use frozen outlets; VLM retains its existing check boundary."""

import sys
from types import ModuleType
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.model import ModelOutletValidationRequest

from test.backend.services import test_model_health_service as legacy_tests


@pytest.fixture
def health(monkeypatch):
    module = sys.modules[legacy_tests.check_model_connectivity.__module__]

    profiles = ModuleType("management.services.model.profiles")
    profiles.validate_model_outlet = AsyncMock(return_value={"ok": True, "error": None})
    monkeypatch.setitem(sys.modules, profiles.__name__, profiles)
    return module, profiles


@pytest.mark.asyncio
@pytest.mark.parametrize("model_type", ["llm", "chat"])
async def test_llm_checks_use_saved_id_revision_and_tenant(health, monkeypatch, model_type):
    module, profiles = health
    monkeypatch.setattr(module, "get_model_by_display_name", Mock(return_value={
        "model_type": model_type, "model_id": 42, "config_revision": 7, "model_name": "Exact/Model",
    }))
    old = AsyncMock()
    monkeypatch.setattr(module, "_check_non_llm_connectivity", old)
    result = await module.check_model_connectivity("chosen", "tenant", model_type)
    request, tenant = profiles.validate_model_outlet.await_args.args
    assert isinstance(request, ModelOutletValidationRequest)
    assert request.outlet_id == 42 and request.expected_revision == 7 and tenant == "tenant"
    assert result == {"connectivity": True, "model_name": "Exact/Model"}
    old.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_llm_check_keeps_existing_envelope_with_safe_category(health, monkeypatch):
    module, profiles = health
    monkeypatch.setattr(module, "get_model_by_display_name", Mock(return_value={
        "model_type": "llm", "model_id": 42, "config_revision": 1, "model_name": "exact",
    }))
    profiles.validate_model_outlet.return_value = {"ok": False, "error": {"category": "model_authentication_error"}}
    assert await module.check_model_connectivity("chosen", "tenant") == {
        "connectivity": False, "model_name": "exact", "error": "model_authentication_error",
    }


@pytest.mark.asyncio
async def test_vlm_check_reuses_original_row_without_llm_profile_validation(health, monkeypatch):
    module, profiles = health
    row = {"model_type": "vlm", "model_id": 43}
    lookup = Mock(return_value=row)
    monkeypatch.setattr(module, "get_model_by_display_name", lookup)
    old = AsyncMock(return_value={"connectivity": True, "model_name": "vision"})
    monkeypatch.setattr(module, "_check_non_llm_connectivity", old)
    assert await module.check_model_connectivity("vision", "tenant", "vlm") == old.return_value
    old.assert_awaited_once_with("vision", "tenant", "vlm", _model=row)
    assert lookup.call_count == 1
    profiles.validate_model_outlet.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_outlet_does_not_probe_any_endpoint(health, monkeypatch):
    module, profiles = health
    monkeypatch.setattr(module, "get_model_by_display_name", Mock(return_value=None))
    with pytest.raises(LookupError, match="MODEL_CONFIGURATION_NOT_FOUND"):
        await module.check_model_connectivity("missing", "tenant")
    profiles.validate_model_outlet.assert_not_awaited()
