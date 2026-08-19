import ast
import json
import re

import pytest
from jinja2 import UndefinedError
from pydantic import ValidationError

from agents.nl2agent_agent import (
    build_nl2agent_system_prompt,
    create_nl2agent_agent_config,
)
from tool_collection.mcp.local_mcp_service import local_mcp_service
from tool_collection.mcp.nl2agent_mcp_tools import (
    FinalConfirmationPayload,
    NL2A_WRAPPER_NAME,
    RECOMMEND_RESOURCES_NAME,
    RecommendResourcesInput,
    RequirementClarificationPayload,
    ResourceCandidate,
    ResourceRequirement,
    SAVE_AGENT_DRAFT_FIELDS_NAME,
    SEARCH_INSTALLED_RESOURCES_NAME,
    SearchInstalledResourcesInput,
    build_nl2a_wrapper,
)


@pytest.mark.parametrize(
    ("language", "heading", "immutable_rule", "description_rule"),
    [
        (
            "en",
            "### Role",
            "`name` and `display_name` are immutable",
            "generate only `description` and `business_description`",
        ),
        (
            "zh",
            "### 核心职责",
            "`name` 和 `display_name` 不可修改",
            "只生成 `description` 和 `business_description`",
        ),
    ],
)
def test_build_nl2agent_system_prompt_configures_existing_draft(
    language,
    heading,
    immutable_rule,
    description_rule,
):
    prompt = build_nl2agent_system_prompt(
        language,
        tool_name="runtime_search",
        recommend_tool_name="runtime_recommend",
        wrapper_name="runtime_wrapper",
        save_tool_name="runtime_save",
        max_results=3,
    )

    assert heading in prompt
    assert immutable_rule in prompt
    assert description_rule in prompt
    assert "runtime_search" in prompt
    assert "runtime_recommend" in prompt
    assert "runtime_wrapper" in prompt
    assert "runtime_save" in prompt
    assert "json.loads" in prompt
    assert "bound_resources" in prompt
    assert "basic_info" in prompt
    assert 'subtype="requirement_clarification"' in prompt
    assert 'subtype="installed_resource_binding"' in prompt
    assert 'subtype="final_confirmation"' in prompt
    assert "agent_id=None" not in prompt
    assert "nl2agent_tool_selection" not in prompt
    assert 'subtype="agent_draft"' not in prompt
    assert 'subtype="local_mcp_recommendation"' not in prompt
    assert "<nl2a>" not in prompt
    assert "```" not in prompt

    description_save = prompt.index('"description":')
    resource_search = prompt.index("raw_result = runtime_search")
    assert description_save < resource_search

    code_blocks = re.findall(r"<code>\n(.*?)\n</code>", prompt, re.DOTALL)
    assert len(code_blocks) == 7
    for code_block in code_blocks:
        ast.parse(code_block)


def test_build_nl2agent_system_prompt_falls_back_to_chinese():
    assert build_nl2agent_system_prompt("fr") == build_nl2agent_system_prompt("zh")


def test_build_nl2agent_system_prompt_rejects_unknown_template_variables(mocker):
    prompt_loader = mocker.patch(
        "agents.nl2agent_agent.get_prompt_template",
        return_value={"system_prompt": "{{ missing_value }}"},
    )

    with pytest.raises(UndefinedError, match="missing_value"):
        build_nl2agent_system_prompt("en")

    prompt_loader.assert_called_once_with("nl2agent", "en")


def test_current_wrapper_models_require_existing_agent_id():
    requirement = ResourceRequirement(
        requirement_id="source",
        query="Find reliable source material",
    )
    assert SearchInstalledResourcesInput(requirements=[requirement]).requirements
    candidate = ResourceCandidate(
        candidate_ref="tool:7",
        resource_type="tool",
        source="LOCAL_TOOL",
        name="search",
        requirement_ids=["source"],
        score=0.9,
    )
    assert RecommendResourcesInput(candidates=[candidate]).recommended_refs == []

    wrapped = build_nl2a_wrapper(
        subtype="requirement_clarification",
        agent_id=42,
        questions=[
            {
                "question_id": "output",
                "question_type": "single_choice",
                "title": "What should the Agent produce?",
                "required": True,
                "options": [{"option_id": "report", "label": "A report"}],
                "allow_other": True,
                "other_input_expanded": True,
            }
        ],
    )
    payload = json.loads(wrapped.split("<nl2a>", 1)[1].split("</nl2a>", 1)[0])
    clarification = RequirementClarificationPayload.model_validate(payload)
    assert clarification.agent_id == 42

    with pytest.raises(ValidationError):
        RequirementClarificationPayload(
            questions=[
                {
                    "question_id": "output",
                    "question_type": "text",
                    "title": "What should the Agent produce?",
                }
            ]
        )


def test_installed_resource_binding_wrapper_preserves_verified_contract():
    candidate = ResourceCandidate(
        candidate_ref="skill:12",
        resource_type="skill",
        source="INSTALLED_SKILL",
        name="daily_report",
        description="Create a daily report",
        requirement_ids=["report"],
        score=0.88,
    )
    wrapped = build_nl2a_wrapper(
        subtype="installed_resource_binding",
        agent_id=42,
        resource_result={
            "status": "success",
            "resources": [
                {
                    "candidate": candidate.model_dump(mode="json"),
                    "recommendation": "recommended",
                    "form_kind": "SKILL_CONFIG",
                    "config": [],
                }
            ],
        },
    )
    payload = json.loads(wrapped.split("<nl2a>", 1)[1].split("</nl2a>", 1)[0])

    assert payload["agent_id"] == 42
    assert payload["resources"][0]["candidate"]["candidate_ref"] == "skill:12"


def test_requirement_clarification_accepts_at_most_five_questions():
    questions = [
        {
            "question_id": f"question-{index}",
            "question_type": "text",
            "title": f"Question {index}",
        }
        for index in range(5)
    ]

    assert len(RequirementClarificationPayload(agent_id=42, questions=questions).questions) == 5
    with pytest.raises(ValidationError, match="at most 5 items"):
        RequirementClarificationPayload(
            agent_id=42,
            questions=[
                *questions,
                {
                    "question_id": "question-5",
                    "question_type": "text",
                    "title": "Question 5",
                },
            ],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["zh", "en"])
async def test_create_nl2agent_agent_config_has_only_current_runtime_tools(language):
    config = create_nl2agent_agent_config(language)
    registered_tools = await local_mcp_service.get_tools()

    assert [tool.name for tool in config.tools] == [
        SEARCH_INSTALLED_RESOURCES_NAME,
        RECOMMEND_RESOURCES_NAME,
        SAVE_AGENT_DRAFT_FIELDS_NAME,
        NL2A_WRAPPER_NAME,
    ]
    assert [tool.description for tool in config.tools] == [
        registered_tools[SEARCH_INSTALLED_RESOURCES_NAME].description,
        registered_tools[RECOMMEND_RESOURCES_NAME].description,
        registered_tools[SAVE_AGENT_DRAFT_FIELDS_NAME].description,
        registered_tools[NL2A_WRAPPER_NAME].description,
    ]
    assert json.loads(config.tools[0].inputs)["agent_id"] == "int"
    assert json.loads(config.tools[1].inputs)["agent_id"] == "int"
    save_inputs = json.loads(config.tools[2].inputs)
    assert save_inputs["agent_id"] == "int"
    assert set(save_inputs["fields"]) == {
        "description",
        "business_description",
        "duty_prompt",
        "constraint_prompt",
        "few_shots_prompt",
        "greeting_message",
        "example_questions",
    }
    assert set(json.loads(config.tools[3].inputs)) == {
        "subtype",
        "agent_id",
        "resource_result",
        "questions",
        "requirements",
        "abandoned_requirement_ids",
    }


def test_final_confirmation_payload_rejects_duplicate_requirement_ids():
    with pytest.raises(ValidationError, match="requirement IDs must be unique"):
        FinalConfirmationPayload(
            agent_id=42,
            agent={
                "name": "research_assistant",
                "display_name": "Research Assistant",
                "description": "Research help",
                "business_description": "Verify and summarize sources",
            },
            requirements=[{"requirement_id": "research", "query": "Research"}],
            abandoned_requirements=[
                {"requirement_id": "research", "query": "Old research"}
            ],
            resources=[],
            prompts={
                "duty_prompt": "Research",
                "constraint_prompt": "",
                "few_shots_prompt": "",
                "greeting_message": "Hello",
                "example_questions": ["What should I research?"],
            },
        )
