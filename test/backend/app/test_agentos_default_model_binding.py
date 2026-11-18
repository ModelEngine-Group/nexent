# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify legacy default aliases are pinned and materialized through AgentOS."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from contracts.agentos import RunModelBinding, TurnModelGeneration
from contracts.model import WorkbenchGenerationConfig
from infrastructure.agent_model_config import create_model_config_from_record, create_tenant_default_model_config
from infrastructure.agent_model_overrides import apply_turn_model_generation
from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent.preparation import evaluation_snapshot
from runtime.agentos import prepared_evaluation
from test.backend.services.model_profile_helpers import canonical_record, stub_resolved_model_catalog


_LEGACY_RECORD = {
    "model_id": 17, "display_name": "configured-provider", "model_name": "test", "model_repo": "",
    "base_url": "https://provider.invalid/v1", "api_key": "private-key",
    "tenant_id": "tenant", "delete_flag": "N", "model_type": "llm", "model_factory": "openai",
    "update_time": "legacy-v1", "temperature": 0.7, "extra_params": {"__custom__": {"private_extension": True}},
}
_ACTOR = ServicePrincipal("user", "tenant")


def resource(alias):
    return SimpleNamespace(agent_id=3, version_no=1, model_alias=alias, subagents=())


@pytest.mark.parametrize("profile", ["standard", "logprobs"])
@pytest.mark.parametrize("explicit_generation", [False, True])
def test_default_alias_roundtrips_canonical_sdk_config(mocker, profile, explicit_generation):
    record = canonical_record(_LEGACY_RECORD)
    stub_resolved_model_catalog(mocker, record)
    mocker.patch.object(evaluation_snapshot, "get_model_records", return_value=[])
    get_default = mocker.patch.object(evaluation_snapshot.tenant_config_manager, "get_model_config", return_value=record)
    read_runtime = mocker.patch.object(prepared_evaluation, "get_model_by_model_id", return_value=record)
    original = create_tenant_default_model_config(record, "main_model", include_logprobs=profile == "logprobs")
    generation = TurnModelGeneration(settings=WorkbenchGenerationConfig(temperature=0.2)) if explicit_generation else None
    effective = apply_turn_model_generation(original, generation, "turn_root_model") if generation else original
    binding = evaluation_snapshot._export_model(
        effective.cite_name, [original, effective] if generation else [original], "tenant", resource(effective.cite_name), {},
        turn_generation=generation, source_alias="main_model" if generation else None,
    )
    assert binding.model_id == 17
    assert binding.tenant_default_profile == (profile if explicit_generation or profile == "logprobs" else None)
    encoded = binding.model_dump_json()
    assert all(value not in encoded for value in ("private-key", "provider.invalid", "private_extension"))
    restored = prepared_evaluation._materialize_model(
        RunModelBinding.model_validate_json(encoded), _ACTOR, resource(effective.cite_name),
    )
    assert restored == effective
    read_runtime.assert_called_once_with(17, "tenant")
    if explicit_generation:
        assert get_default.call_args.kwargs["tenant_id"] == "tenant"
    else:
        get_default.assert_not_called()


def test_real_catalog_model_wins_when_its_name_matches_reserved_alias(mocker):
    record = canonical_record({**_LEGACY_RECORD, "display_name": "main_model"})
    listed = create_model_config_from_record(record)
    default = create_tenant_default_model_config(canonical_record(_LEGACY_RECORD), "main_model", include_logprobs=False)
    mocker.patch.object(evaluation_snapshot, "get_model_records", return_value=[record])
    stub_resolved_model_catalog(mocker, record)
    get_default = mocker.patch.object(evaluation_snapshot.tenant_config_manager, "get_model_config")
    binding = evaluation_snapshot._export_model("main_model", [listed, default], "tenant", resource("main_model"), {})
    assert binding.tenant_default_profile is None
    get_default.assert_not_called()


@pytest.mark.parametrize("invalid", ["other_tenant", "configuration_changed", "wrong_type"])
def test_compiler_refuses_to_pin_a_different_default_model(mocker, invalid):
    selected = create_tenant_default_model_config(canonical_record(_LEGACY_RECORD), "sub_model", include_logprobs=False)
    record = {**_LEGACY_RECORD}
    if invalid == "other_tenant":
        record["tenant_id"] = "other"
    elif invalid == "wrong_type":
        record["model_type"] = "embedding"
    else:
        record["model_name"] = "changed"
    if invalid != "wrong_type":
        record = canonical_record(record)
    from management.services.agent.preparation import model_bindings

    mocker.patch.object(model_bindings, "get_model_by_model_id", return_value=record)
    mocker.patch.object(model_bindings, "read_agent_model_overrides", return_value={})
    with pytest.raises(ValueError):
        evaluation_snapshot._export_model("sub_model", [selected], "tenant", resource("sub_model"), {})


@pytest.mark.parametrize(("change", "status"), [({"update_time": "v2"}, 409), ({"tenant_id": "other"}, 404)])
def test_runtime_rechecks_default_model_identity_and_revision(mocker, change, status):
    mocker.patch.object(prepared_evaluation, "get_model_by_model_id", return_value={**_LEGACY_RECORD, **change})
    binding = RunModelBinding(model_id=17, alias="main_model", revision="legacy-v1", tenant_default_profile="standard")
    with pytest.raises(HTTPException) as exc:
        prepared_evaluation._materialize_model(binding, _ACTOR, resource("main_model"))
    assert exc.value.status_code == status
