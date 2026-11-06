# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""SU-AC-06: all Agent modes share root-only profile preferences."""

from copy import deepcopy

import pytest
from contracts.errors.exceptions import ModelOutletValidationError
from management.services.agent.preparation.inputs import _materialize_runtime_skill_snapshot
from management.services.agent.preparation.run import apply_root_model_preferences
from nexent.core.agents.agent_model import AgentConfig, ModelConfig
from management.services.model.profiles import build_outlet_draft
from test.backend.services.test_model_profile_service import draft_request


@pytest.fixture
def profile():
    value, _ = build_outlet_draft(draft_request(parameter_values={"enable_thinking": True, "reasoning_budget_tokens": 64}), "tenant")
    connection = value.connection.model_copy(update={"credential_ref": value.connection.credential_ref.model_copy(update={"model_id": 42})})
    return value.model_copy(update={"outlet_id": 42, "connection": connection})


@pytest.mark.parametrize("values", [{"temperature": 0, "top_p": 0.8}, {"enable_thinking": False}, {"reasoning_budget_tokens": 128}])
def test_su_ac_06_only_root_changes_and_all_persisted_defaults_remain_intact(profile, values):
    child = AgentConfig(name="child", description="", tools=[], model_name="shared")
    root = AgentConfig(name="root", description="", tools=[], model_name="shared", managed_agents=[child])
    shared = ModelConfig(cite_name="shared", model_name="provider/model", url="https://example.invalid", resolved_profile=profile)
    models = [shared]
    before = deepcopy(profile.model_dump())
    apply_root_model_preferences(models, root, {"42": values}, outlet_profiles={42: profile}, agent_overrides={})
    assert root.model_name.startswith("conversation_root_model_")
    assert child.model_name == "shared"
    assert shared.resolved_profile.model_dump() == before
    for key, value in values.items():
        assert models[-1].resolved_profile.parameter_values[key] == value
    if values.get("enable_thinking") is False:
        assert "reasoning_budget_tokens" not in models[-1].resolved_profile.parameter_values


def test_su_ac_04_other_model_preferences_do_not_affect_selected_root(profile):
    root = AgentConfig(name="root", description="", tools=[], model_name="shared")
    models = [ModelConfig(cite_name="shared", model_name="provider/model", url="https://example.invalid", resolved_profile=profile)]
    apply_root_model_preferences(models, root, {"43": {"temperature": 0}})
    assert len(models) == 1 and root.model_name == "shared"


def test_su_ac_05_conflicting_values_cannot_mutate_aliases_or_defaults(profile):
    root = AgentConfig(name="root", description="", tools=[], model_name="shared")
    models = [ModelConfig(cite_name="shared", model_name="provider/model", url="https://example.invalid", resolved_profile=profile)]
    with pytest.raises(ModelOutletValidationError):
        apply_root_model_preferences(models, root, {"42": {"enable_thinking": False, "reasoning_budget_tokens": 64}})
    assert len(models) == 1 and root.model_name == "shared"


def test_ut_be_wb_011_materializes_an_immutable_run_skill_snapshot(tmp_path):
    """UT-BE-WB-011: materialization is immutable and run-scoped."""
    source = [{
        "name": "invoice-skill",
        "files": [
            ("SKILL.md", b"---\nname: invoice-skill\ndescription: Test\n---\nGuide"),
            ("scripts/run.py", b"print('snapshot')"),
        ],
    }]

    effective = _materialize_runtime_skill_snapshot(
        source,
        str(tmp_path / "run"),
        "tenant",
    )

    snapshot_root = effective[0]["_snapshot_root"]
    assert (tmp_path / "run" / ".skill_snapshot" / "tenant" / "invoice-skill" / "scripts" / "run.py").read_bytes() == b"print('snapshot')"
    assert "files" not in effective[0]
    assert "_snapshot_root" not in source[0]
    assert source[0]["files"][1][1] == b"print('snapshot')"
    assert snapshot_root == str((tmp_path / "run" / ".skill_snapshot").resolve())
