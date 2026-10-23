# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""External import normalization and canonical internal model boundaries."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from contracts.agent import AgentImportRequest, ExportAndImportAgentInfo
from infrastructure.agent_prompt import normalize_imported_agent_bundle, normalize_imported_agent_prompt


@pytest.fixture
def agent_payload():
    return dict(agent_id=1, name="test-agent", description="Test agent", max_steps=5,
                provide_run_summary=False, enabled=True, tools=[], managed_agents=[])


@pytest.mark.parametrize("fields,expected", [
    ({}, None), ({"prompt": None}, None), ({"prompt": ""}, ""),
    ({"prompt": " exact\n  prompt "}, " exact\n  prompt "),
    ({"duty_prompt": "Purpose", "constraint_prompt": "Rule", "few_shots_prompt": "Example"},
     "# Responsibilities\nPurpose\n\n# Constraints\nRule\n\n# Examples\nExample"),
    ({"prompt": "Purpose", "constraints_prompt": "Rule", "few_shot_prompts": "Example"},
     "# Responsibilities\nPurpose\n\n# Constraints\nRule\n\n# Examples\nExample"),
    ({"constraint_prompt": "Rule"}, "# Constraints\nRule"),
    ({"few_shot_prompts": "Example"}, "# Examples\nExample"),
    ({"prompt": "Purpose", "constraint_prompt": " \n", "few_shots_prompt": None}, "Purpose"),
    ({"prompt": "Same", "duty_prompt": "Same", "constraint_prompt": "Rule", "constraints_prompt": "Rule"},
     "# Responsibilities\nSame\n\n# Constraints\nRule"),
])
def test_external_import_preserves_content_and_does_not_mutate_input(agent_payload, fields, expected):
    agent_payload.update(fields)
    bundle = {"agent_id": 1, "agent_info": {"1": agent_payload, "2": {**agent_payload, "agent_id": 2}},
              "mcp_info": []}
    original = deepcopy(bundle)
    request = AgentImportRequest(agent_info=bundle)
    for agent in request.agent_info.agent_info.values():
        assert agent.prompt == expected
        exported = agent.model_dump()
        assert not set(exported) & {"duty_prompt", "constraint_prompt", "constraints_prompt", "few_shots_prompt", "few_shot_prompts"}
        assert ExportAndImportAgentInfo.model_validate(exported).model_dump() == exported
    assert bundle == original
    normalized = normalize_imported_agent_bundle(bundle)
    assert normalize_imported_agent_bundle(normalized) == normalized


@pytest.mark.parametrize("canonical,legacy", [
    ("prompt", "duty_prompt"), ("constraint_prompt", "constraints_prompt"),
    ("few_shots_prompt", "few_shot_prompts"),
])
def test_import_rejects_conflicting_aliases_without_changing_source(canonical, legacy):
    fields = {canonical: "New", legacy: "Old"}
    with pytest.raises(ValueError, match="must not conflict"):
        normalize_imported_agent_prompt(fields)
    assert fields == {canonical: "New", legacy: "Old"}


@pytest.mark.parametrize("field", ["prompt", "duty_prompt", "constraint_prompt", "constraints_prompt", "few_shots_prompt", "few_shot_prompts"])
@pytest.mark.parametrize("value", [7, [], {}, True])
def test_external_import_rejects_invalid_prompt_types(agent_payload, field, value):
    agent_payload[field] = value
    with pytest.raises(ValidationError, match="must be a string or null"):
        AgentImportRequest(agent_info={"agent_id": 1, "agent_info": {"1": agent_payload}, "mcp_info": []})


@pytest.mark.parametrize("field", ["duty_prompt", "constraint_prompt", "constraints_prompt", "few_shots_prompt", "few_shot_prompts"])
def test_canonical_snapshot_model_does_not_merge_extra_fields(agent_payload, field):
    agent = ExportAndImportAgentInfo(**agent_payload, prompt="Canonical", **{field: "Extra"})
    assert agent.prompt == "Canonical"
    assert field not in agent.model_dump()


@pytest.mark.parametrize("value", [None, "invalid", [], {"agent_info": []}, {"agent_info": {"1": "invalid"}}])
def test_import_rejects_malformed_bundles(value):
    with pytest.raises(ValidationError):
        AgentImportRequest(agent_info=value)


def test_import_preserves_existing_model_instance(agent_payload):
    agent = ExportAndImportAgentInfo(**agent_payload, prompt="Exact")
    assert ExportAndImportAgentInfo.model_validate(agent) is agent
