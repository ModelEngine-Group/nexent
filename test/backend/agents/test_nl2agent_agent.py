import ast
import json
import re
from unittest.mock import MagicMock

import pytest
from jinja2 import UndefinedError
from nexent.core.agents.context import ContextItemInput, ContextManager, ContextManagerConfig
from pydantic import ValidationError
from smolagents import CodeAgent
from smolagents.memory import TaskStep

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

    if language == "en":
        assert "### State And Completion Rules" in prompt
        assert "They never prove that its configuration is complete" in prompt
        assert "an empty-description draft must produce" in prompt
        assert "Configuration is complete only after descriptions are saved" in prompt
        assert "Never produce a plain final answer" in prompt
        assert "Weather Assistant" not in prompt
        assert "Describe the tasks this Agent must perform" not in prompt
        assert '"question_id": "expected_output"' in prompt
    else:
        assert "### 状态判定与完成标准" in prompt
        assert "不证明该 Agent 已完成配置" in prompt
        assert "空描述草稿必须先输出一次" in prompt
        assert "只有描述已保存、资源需求已绑定或明确放弃" in prompt
        assert "禁止输出普通最终答案" in prompt
        assert "天气助手" not in prompt
        assert "请详细说明这个智能体需要完成的任务" not in prompt
        assert '"question_id": "expected_output"' in prompt

    description_save = prompt.index('"description":')
    resource_search = prompt.index("raw_result = runtime_search")
    assert description_save < resource_search

    code_blocks = re.findall(r"<code>\n(.*?)\n</code>", prompt, re.DOTALL)
    assert len(code_blocks) == 8
    for code_block in code_blocks:
        ast.parse(code_block)

    few_shots_save = next(
        code_block
        for code_block in code_blocks
        if 'fields={"few_shots_prompt": few_shots}' in code_block
    )
    assert r"\x3ccode>" in few_shots_save
    assert r"\x3c/code>" in few_shots_save
    assert r"Observation\x3a" in few_shots_save
    assert "<code>" not in few_shots_save
    assert "</code>" not in few_shots_save
    assert "Observation:" not in few_shots_save

    few_shots_assignment = ast.parse(few_shots_save).body[0]
    assert isinstance(few_shots_assignment, ast.Assign)
    stored_few_shots = ast.literal_eval(few_shots_assignment.value)
    assert "<code>" in stored_few_shots
    assert "</code>" in stored_few_shots
    assert "Observation:" in stored_few_shots


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
    assert config.instructions is None
    assert len(config.context_items) == 1
    prompt_context = config.context_items[0]
    assert prompt_context.id == "system:nl2agent_prompt"
    assert prompt_context.type.value == "system"
    assert prompt_context.source == ("prompt:nl2agent",)
    assert prompt_context.priority == 100
    assert prompt_context.metadata == {
        "authority": "platform",
        "layout_order": -1,
    }
    assert prompt_context.content["text"] == build_nl2agent_system_prompt(language)


def test_nl2agent_explicit_system_context_reaches_final_model_messages():
    config = create_nl2agent_agent_config("zh")
    runtime_agent = CodeAgent(
        tools=[],
        model=MagicMock(),
        instructions=config.instructions,
    )
    verified_state = ContextItemInput(
        id="system:nl2agent_bound_resources",
        type="system",
        content={"text": "Verified database binding facts: agent_id=42"},
        metadata={"authority": "tenant"},
    )
    manager = ContextManager(ContextManagerConfig(token_threshold=100000))

    run_context = manager.prepare_run_context(
        memory=runtime_agent.memory,
        fallback_system_prompt=runtime_agent.system_prompt,
        items=[*config.context_items, verified_state],
    )
    runtime_agent.memory.steps.append(TaskStep(task="配置这个草稿"))
    final_context = manager.assemble_final_context(
        model=None,
        memory=runtime_agent.memory,
        current_run_start_idx=0,
        run_context=run_context,
    )
    message_texts = [
        "".join(
            part.get("text", "")
            for part in message["content"]
            if isinstance(part, dict)
        )
        for message in final_context.messages
    ]

    assert [item.id for item in run_context.items] == [
        "system:nl2agent_prompt",
        "system:nl2agent_bound_resources",
    ]
    assert all(item.id != "system:fallback" for item in run_context.items)
    assert [message["role"] for message in final_context.messages] == [
        "system",
        "system",
        "user",
    ]
    assert "### 核心职责" in message_texts[0]
    assert "空描述草稿必须先输出一次 `requirement_clarification` 卡" in message_texts[0]
    assert message_texts[1] == "Verified database binding facts: agent_id=42"
    assert message_texts[2] == "配置这个草稿"


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
