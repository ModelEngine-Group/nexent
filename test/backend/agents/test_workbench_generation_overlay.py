# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Functional tests for root-only Workbench generation overrides."""

import pytest
from pydantic import ValidationError

from management.services.agent.preparation.inputs import _materialize_runtime_skill_snapshot
from management.services.agent.preparation.run import apply_root_generation_overlay
from contracts.agent import WorkbenchGenerationConfig
from nexent.core.agents.agent_model import AgentConfig, ModelConfig

EFFORT_CAPABILITY = {"status": "supported", "control": "effort", "levels": ["none", "minimal", "low", "medium", "high", "xhigh", "max"]}


def test_workbench_generation_schema_defaults_effort_to_low():
    assert WorkbenchGenerationConfig().thinking_effort == "low"


@pytest.mark.parametrize("effort", ["auto", "none", "minimal", "low", "medium", "high", "xhigh", "max"])
def test_complete_workbench_effort_schema_and_root_overlay(effort):
    config = WorkbenchGenerationConfig(
        deep_thinking=True, thinking_effort=effort, temperature=0.6, top_p=0.83,
        requested_output_tokens=2000,
    )
    assert WorkbenchGenerationConfig.model_validate(config.model_dump()) == config
    root = AgentConfig(name="root", description="", tools=[], model_name="shared")
    original = ModelConfig(cite_name="shared", model_name="provider/model", url="https://example.invalid", reasoning_capability=EFFORT_CAPABILITY,
                           temperature=0.2, top_p=0.9, reasoning_effort="high")
    models = [original]
    apply_root_generation_overlay(models, root, config.model_dump())
    assert models[-1].reasoning_effort == ("high" if effort == "auto" else effort)
    assert models[-1].temperature == 0.6
    assert models[-1].top_p == 0.83
    assert original.reasoning_effort == "high"
    assert original.temperature == 0.2
    apply_root_generation_overlay(models, root, {"deep_thinking": False, "thinking_effort": effort})
    assert models[-1].reasoning_effort is None


@pytest.mark.parametrize("effort", ["invalid", "", 1])
def test_workbench_effort_schema_rejects_unknown_values(effort):
    with pytest.raises(ValidationError):
        WorkbenchGenerationConfig(thinking_effort=effort)


def test_neutral_generation_overlay_changes_only_root_alias():
    """UT-BE-WB-019: runtime generation values affect only the effective root."""
    child = AgentConfig(
        name="child",
        description="",
        tools=[],
        model_name="shared_model",
    )
    root = AgentConfig(
        name="root",
        description="",
        tools=[],
        model_name="shared_model",
        managed_agents=[child],
    )
    shared = ModelConfig(
        cite_name="shared_model",
        model_name="provider/model",
        url="https://example.invalid", reasoning_capability=EFFORT_CAPABILITY,
        temperature=0.1,
        top_p=0.95,
    )
    models = [shared]

    apply_root_generation_overlay(
        models,
        root,
        {"deep_thinking": False, "temperature": 0.7, "top_p": 0.8},
    )

    assert root.model_name == "workbench_root_model"
    assert child.model_name == "shared_model"
    assert shared.temperature == 0.1
    assert models[-1].temperature == 0.7
    assert models[-1].top_p == 0.8
    assert models[-1].extra_body == {"enable_thinking": False}


def test_thinking_settings_apply_to_root_without_mutating_child_model():
    root = AgentConfig(name="root", description="", tools=[], model_name="shared_model")
    shared = ModelConfig(
        cite_name="shared_model",
        model_name="provider/model",
        url="https://example.invalid", reasoning_capability=EFFORT_CAPABILITY,
        extra_body={"existing": "value"},
        reasoning_effort="high",
        reasoning_budget_tokens=2048,
    )
    models = [shared]
    apply_root_generation_overlay(
        models,
        root,
        {"deep_thinking": True, "thinking_effort": "low"},
    )
    assert root.model_name == "workbench_root_model"
    assert shared.extra_body == {"existing": "value"}
    assert shared.reasoning_effort == "high"
    assert models[-1].extra_body == {
        "existing": "value",
        "enable_thinking": True,
    }
    assert models[-1].enable_thinking is True
    assert models[-1].reasoning_effort == "low"
    assert models[-1].reasoning_budget_tokens is None


def test_enabling_thinking_without_explicit_effort_inherits_provider_default():
    root = AgentConfig(name="root", description="", tools=[], model_name="shared_model")
    models = [ModelConfig(
        cite_name="shared_model",
        model_name="provider/model",
        url="https://example.invalid", reasoning_capability=EFFORT_CAPABILITY,
    )]

    apply_root_generation_overlay(models, root, {"deep_thinking": True})

    assert models[-1].reasoning_effort is None
    assert models[-1].extra_body == {"enable_thinking": True}


def test_disabling_thinking_drops_stale_effort_from_root_only():
    root = AgentConfig(name="root", description="", tools=[], model_name="shared_model")
    shared = ModelConfig(
        cite_name="shared_model",
        model_name="provider/model",
        url="https://example.invalid", reasoning_capability=EFFORT_CAPABILITY,
        extra_body={"enable_thinking": True, "reasoning_effort": "high"},
        reasoning_effort="high",
        reasoning_budget_tokens=2048,
    )
    models = [shared]
    apply_root_generation_overlay(
        models,
        root,
        {"deep_thinking": False, "thinking_effort": "medium"},
    )
    assert shared.extra_body == {"enable_thinking": True, "reasoning_effort": "high"}
    assert models[-1].extra_body == {"enable_thinking": False}
    assert models[-1].enable_thinking is False
    assert models[-1].reasoning_effort is None
    assert models[-1].reasoning_budget_tokens is None


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
