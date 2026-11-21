# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime probes frozen outlets locally; non-LLM checks retain their original boundary."""

from unittest.mock import AsyncMock, Mock

import pytest

from nexent.core.model_service.profiles.configuration import build_outlet_draft
from nexent.core.model_service.profiles.configuration_inputs import ModelProfilePreviewRequest
from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile
from nexent.core.model_service.registry import model_service_references
from infrastructure.rdb import outlets
from runtime.model import health as module, profile_probe


@pytest.fixture
def health(monkeypatch):
    profile, _ = build_outlet_draft(ModelProfilePreviewRequest(request_model_id="Exact/Model",
        provider_info={"base_url": "https://provider.invalid/v1"}), "tenant")
    data = profile.model_dump(mode="json")
    data["outlet_id"] = data["connection"]["credential_ref"]["model_id"] = 42
    data["config_revision"] = 7
    profile = profile.__class__.model_validate(data)
    row = encode_resolved_model_profile(profile, registered_references=model_service_references())
    row.update(model_id=42, api_key="runtime-secret", http_headers={"X-Workspace": "controlled"})
    lookup = Mock(return_value=row)
    probe = AsyncMock(return_value={"ok": True, "error": None})
    update = Mock()
    monkeypatch.setattr(module, "get_model_by_display_name", lookup)
    monkeypatch.setattr(profile_probe, "probe_model_profile", probe)
    monkeypatch.setattr(outlets, "update_model_outlet_connectivity", update)

    async def inline(_name, fn, *args, **kwargs):
        assert kwargs == {"lane": "control-io", "owner": "runtime.model"}
        return fn(*args)

    monkeypatch.setattr(module, "run_blocking", inline)
    return row, profile, lookup, probe, update


@pytest.mark.asyncio
@pytest.mark.parametrize("model_type", ["llm", "chat"])
async def test_llm_checks_use_saved_id_revision_and_tenant(health, monkeypatch, model_type):
    row, profile, lookup, probe, update = health
    # The request alias does not change the canonical saved outlet type.
    old = AsyncMock()
    monkeypatch.setattr(module, "_check_non_llm_connectivity", old)
    assert await module.check_model_connectivity("chosen", "tenant", model_type) == {
        "connectivity": True, "model_name": "Exact/Model"}
    lookup.assert_called_once_with("chosen", tenant_id="tenant", model_type=model_type)
    probe.assert_awaited_once_with(profile, "runtime-secret", http_headers=row["http_headers"])
    update.assert_called_once_with(42, "tenant", 7, "available")
    old.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_llm_check_keeps_existing_envelope_with_safe_category(health):
    _, _, _, probe, update = health
    probe.return_value = {"ok": False, "error": {"category": "model_authentication_error"}}
    assert await module.check_model_connectivity("chosen", "tenant") == {
        "connectivity": False, "model_name": "Exact/Model", "error": "model_authentication_error"}
    update.assert_called_once_with(42, "tenant", 7, "unavailable")


@pytest.mark.asyncio
async def test_vlm_check_reuses_original_row_without_llm_profile_validation(health, monkeypatch):
    row, _, lookup, probe, update = health
    row["model_type"] = "vlm"
    old = AsyncMock(return_value={"connectivity": True, "model_name": "vision"})
    monkeypatch.setattr(module, "_check_non_llm_connectivity", old)
    assert await module.check_model_connectivity("vision", "tenant", "vlm") == old.return_value
    old.assert_awaited_once_with("vision", "tenant", "vlm", _model=row)
    assert lookup.call_count == 1
    probe.assert_not_awaited()
    update.assert_not_called()


@pytest.mark.asyncio
async def test_missing_outlet_does_not_probe_any_endpoint(health):
    _, _, lookup, probe, update = health
    lookup.return_value = None
    with pytest.raises(LookupError, match="MODEL_CONFIGURATION_NOT_FOUND"):
        await module.check_model_connectivity("missing", "tenant")
    probe.assert_not_awaited()
    update.assert_not_called()


@pytest.mark.asyncio
async def test_inventory_probe_does_not_update_the_saved_outlet(health):
    _, _, _, probe, update = health
    assert (await module.check_model_connectivity("chosen", "tenant", persist_status=False))["connectivity"] is True
    probe.assert_awaited_once()
    update.assert_not_called()
