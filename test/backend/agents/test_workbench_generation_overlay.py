"""Functional tests for root-only Workbench generation overrides."""

from agents.create_agent_info import (
    _materialize_runtime_skill_snapshot,
    apply_root_generation_overlay,
)
from agents.create_agent_info import WorkbenchError
import pytest
from nexent.core.agents.agent_model import AgentConfig, ModelConfig


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
        url="https://example.invalid",
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
    assert models[-1].extra_body == shared.extra_body


def test_provider_specific_thinking_requires_external_resolver():
    root = AgentConfig(name="root", description="", tools=[], model_name="shared_model")
    with pytest.raises(WorkbenchError, match="GENERATION_CONFIG_RESOLVER_UNAVAILABLE"):
        apply_root_generation_overlay([], root, {"deep_thinking": True})
    assert root.model_name == "shared_model"


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
