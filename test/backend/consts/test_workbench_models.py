"""Functional acceptance tests for Workbench wire contracts."""

import pytest
from pydantic import ValidationError

from backend.consts.model import AgentRequest, WorkbenchSessionConfig


def _single_agent_payload() -> dict:
    return {
        "schema_version": 3,
        "mode": "single_agent_chat",
        "agent_mounts": [{"agent_id": 7, "version_no": 2}],
        "skill_mounts": [{"skill_id": 11, "config_values": {"region": "cn"}}],
    }


def test_ut_be_wb_001_single_agent_mode_requires_exactly_one_root():
    """UT-BE-WB-001/UT-BE-WB-002: single-Agent mode rejects invalid root counts."""
    for mounts in ([], [{"agent_id": 1}, {"agent_id": 2}]):
        payload = _single_agent_payload()
        payload["agent_mounts"] = mounts
        with pytest.raises(ValidationError):
            WorkbenchSessionConfig.model_validate(payload)


def test_ut_be_wb_024_multi_agent_boundary_is_explicit():
    """UT-BE-WB-024: multi-Agent declarations have a distinct mode contract."""
    config = WorkbenchSessionConfig.model_validate({
        "mode": "multi_agent_chat",
        "agent_mounts": [{"agent_id": 1}, {"agent_id": 2}],
    })
    assert config.mode == "multi_agent_chat"


def test_ut_be_wb_008_skill_mounts_are_a_unique_full_selection():
    """UT-BE-WB-008: duplicate Skill identities cannot enter canonical state."""
    payload = _single_agent_payload()
    payload["skill_mounts"] = [
        {"skill_id": 11, "config_values": {}},
        {"skill_id": 11, "config_values": {}},
    ]
    with pytest.raises(ValidationError):
        WorkbenchSessionConfig.model_validate(payload)


def test_ut_be_wb_020_unknown_canonical_fields_are_rejected():
    """UT-BE-WB-020: v3 canonical config rejects silent schema drift."""
    payload = _single_agent_payload()
    payload["resolved_agents"] = []
    with pytest.raises(ValidationError):
        WorkbenchSessionConfig.model_validate(payload)


def test_ut_be_wb_021_creation_modes_reject_runtime_resources():
    """UT-BE-WB-018/UT-BE-WB-021: creation modes reject runtime resources."""
    with pytest.raises(ValidationError):
        WorkbenchSessionConfig.model_validate({
            "mode": "skill_create",
            "skill_mounts": [{"skill_id": 1}],
        })


def test_ut_be_wb_025_agent_request_requires_explicit_workbench_entrypoint():
    """UT-BE-WB-025: Workbench payload cannot silently use the legacy path."""
    with pytest.raises(ValidationError):
        AgentRequest(query="hello", workbench=_single_agent_payload())
    request = AgentRequest(
        query="hello",
        entrypoint="workbench",
        workbench=_single_agent_payload(),
    )
    assert request.workbench and request.workbench.schema_version == 3
