# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Actual backend bridge restores one saved row without catalog recomposition."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest
from nexent.core.concurrency.cancellation import RunCancellationScope
from nexent.core.model_service.profiles.outlet_storage import (
    ProfileStorageError,
    encode_resolved_model_profile,
)
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from nexent.core.model_service.registry import model_service_references


@pytest.fixture
def bridge(monkeypatch):
    collaborators = {
        "management.db.model.repository": {"get_model_by_model_id": MagicMock()},
        "management.services.configuration.tenant.settings": {"get_model_name_from_config": lambda cfg: cfg.get("model_name"),
                               "tenant_config_manager": MagicMock()},
        "consts.const": {"MODEL_CONFIG_MAPPING": {"llm": "llm"}},
    }
    for name, values in collaborators.items():
        module = ModuleType(name)
        module.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, module)
    path = Path(__file__).resolve().parents[4] / "backend/management/services/model/adapter.py"
    spec = importlib.util.spec_from_file_location("_snapshot_hydration_bridge", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def saved_row(openai_profile):
    data = openai_profile.model_dump()
    registry = model_service_references()
    for key in ("auth", "code_converter", "native_converter"):
        data["bindings"][key] = registry[key][0].model_dump()
    data["outlet_id"] = 42
    data["connection"]["credential_ref"]["model_id"] = 42
    data["parameter_rules"] = [rule for rule in data["parameter_rules"] if rule["key"] != "temperature"]
    data["parameter_rules"].append({
        "key": "temperature", "schema": {"type": "number", "minimum": 0, "maximum": 2},
        "visible": True, "editable": True, "required": False,
        "allowed_scopes": ["outlet", "conversation"], "ui_group": "sampling", "owner": "provider",
        "source": {"ref": "controlled_rule", "version": 1},
        "api_binding": {"path": "/temperature", "transform_ref": "identity_v1", "transform_version": 1},
    })
    data["parameter_values"]["temperature"] = 0.7
    profile = openai_profile.__class__.model_validate(data)
    row = encode_resolved_model_profile(profile, registered_references=registry)
    row["api_key"] = "controlled-key"
    row["model_repo"] = "ignored-prefix"
    return row, profile


def test_restore_uses_row_only_and_preserves_exact_model_identity(bridge, saved_row, monkeypatch):
    row, original = saved_row
    monkeypatch.setattr("nexent.core.model_service.profiles.resolver.load_profile_catalog",
                        lambda: pytest.fail("Runtime must not load TOML"))
    restored = bridge.restore_model_snapshot(row, original.identity.tenant_id)
    assert restored == original
    assert restored.identity.request_model_id == row["model_name"]
    assert "api_key" not in restored.model_dump()
    row["temperature"] = 0.9
    assert restored.parameter_values["temperature"] == 0.7


@pytest.mark.parametrize("invalid", ["tenant", "version", "partial"])
def test_restore_rejects_wrong_tenant_unavailable_versions_and_partial_rows(bridge, saved_row, invalid):
    row, profile = saved_row
    tenant_id = profile.identity.tenant_id
    if invalid == "tenant":
        tenant_id = "other"
    elif invalid == "version":
        row["resolved_profile"]["bindings"]["native_converter"]["version"] = 2
    else:
        row["profile_schema_version"] = None
    with pytest.raises(ProfileStorageError, match="PROFILE_STORAGE_INVALID"):
        bridge.restore_model_snapshot(row, tenant_id)


@pytest.mark.parametrize("modality", ["llm", "llm_long_context"])
def test_context_uses_frozen_row_credentials_scope_and_validated_explicit_overrides(bridge, saved_row, modality):
    row, profile = saved_row
    scope = RunCancellationScope()
    context = bridge._config_to_context(row, modality, "llm", profile.identity.tenant_id,
                                       temperature=0, cancellation_scope=scope)
    assert context.resolved_profile.parameter_values["temperature"] == 0
    assert context.model_name == profile.identity.request_model_id
    assert context.cancellation_scope is scope
    assert context.api_key == "controlled-key"
    row["api_key"] = "later-key"
    assert context.api_key == "controlled-key"
    adapter = bridge.get_gateway().get_adapter(context)
    adapter._build_model()
    assert adapter._model.profile == context.resolved_profile


def test_invalid_business_override_is_not_silently_corrected(bridge, saved_row):
    row, profile = saved_row
    with pytest.raises(ParameterValidationError):
        bridge._config_to_context(row, "llm", "llm", profile.identity.tenant_id, temperature=999)
    assert row["temperature"] == 0.7


def test_legacy_row_is_only_a_temporary_draft_path(bridge):
    assert bridge.restore_model_snapshot({"model_name": "legacy"}, "tenant") is None


def test_persisted_unmigrated_llm_requires_migration_but_vlm_stays_legacy(bridge):
    from contracts.errors.exceptions import ModelOutletValidationError

    with pytest.raises(ModelOutletValidationError) as error:
        bridge.restore_model_snapshot({"model_id": 42, "model_type": "llm"}, "tenant")
    assert error.value.category == "PROFILE_MIGRATION_REQUIRED"
    assert bridge.restore_model_snapshot({"model_id": 43, "model_type": "vlm"}, "tenant") is None
