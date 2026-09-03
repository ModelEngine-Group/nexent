import ast
import json
import re
from unittest.mock import MagicMock

import pytest
from jinja2 import UndefinedError
from nexent.core.agents.context import ContextItemInput, ContextManager, ContextManagerConfig
from nexent.core.tools.parallel_executor import ParallelExecutorTool
from pydantic import ValidationError
from smolagents import CodeAgent
from smolagents.memory import TaskStep

from agents.nl2agent_agent import (
    build_nl2agent_system_prompt,
    create_nl2agent_agent_config,
)
from tool_collection.mcp.local_mcp_service import local_mcp_service
from tool_collection.mcp.nl2agent_mcp_tools import (
    AgentDraftFields,
    NL2A_WRAPPER_NAME,
    RECOMMEND_RESOURCES_NAME,
    RecommendResourcesInput,
    RequirementClarificationPayload,
    ResourceCandidate,
    ResourceRequirement,
    SAVE_AGENT_DRAFT_FIELDS_NAME,
    SEARCH_INSTALLED_RESOURCES_NAME,
    SEARCH_UNINSTALLED_RESOURCES_NAME,
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
            "generate only `description`",
        ),
        (
            "zh",
            "### 核心职责",
            "`name` 和 `display_name` 不可修改",
            "只生成 `description`",
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
    assert "business_description" not in prompt
    assert 'subtype="requirement_clarification"' in prompt
    assert 'subtype="installed_resource_binding"' in prompt
    assert 'subtype="final_confirmation"' not in prompt
    assert "agent_generation_completed" in prompt
    assert "agent_id=None" not in prompt
    assert "nl2agent_tool_selection" not in prompt
    assert 'subtype="agent_draft"' not in prompt
    assert 'subtype="local_mcp_recommendation"' not in prompt
    assert "<nl2a>" not in prompt
    assert "```" not in prompt

    if language == "en":
        assert "enter the Resource-Dependent Prompt Generation stage" in prompt
        assert "Resource-Dependent Prompt Generation must atomically regenerate" in prompt
        assert "### State And Completion Rules" in prompt
        assert "They never prove that its configuration is complete" in prompt
        assert "For `full_generation`, if the current input is not a submitted" in prompt
        assert "Partial tasks are exempt" in prompt
        assert "Configuration is complete only after the description is saved" in prompt
        assert "before receiving `agent_generation_completed`" in prompt
        assert "### Completion Summary" in prompt
        assert "New Agent summary:" in prompt
        assert "### Atomic Action Contract" in prompt
        assert "at most one short reasoning sentence" in prompt
        assert 'equal to `["duty_prompt"]`' in prompt
        assert "exactly one concise Think-Code example" in prompt
        assert "Weather Assistant" not in prompt
        assert "Describe the tasks this Agent must perform" not in prompt
        assert '"question_id": "expected_output"' in prompt
    else:
        assert "资源依赖 Prompt 生成" in prompt
        assert "修订总结" in prompt
        assert "### 状态判定与完成标准" in prompt
        assert "不证明该 Agent 已完成配置" in prompt
        assert "对 `full_generation`，如果当前输入不是已提交的" in prompt
        assert "局部任务不受此规则影响" in prompt
        assert "只有描述已保存、资源需求已安装并绑定或明确放弃" in prompt
        assert "在收到 `agent_generation_completed` 前，不得输出普通完成说明" in prompt
        assert "### 完成总结" in prompt
        assert "新智能体已完成生成" in prompt
        assert "### 原子动作输出契约" in prompt
        assert "`<code>` 前最多只写一句简短思考" in prompt
        assert '`updated_fields` 是 `["duty_prompt"]`' in prompt
        assert "只编写一个紧凑的“思考-代码”示例" in prompt
        assert "天气助手" not in prompt
        assert "请详细说明这个智能体需要完成的任务" not in prompt
        assert '"question_id": "expected_output"' in prompt

    description_save = prompt.index('"description":')
    resource_search = prompt.index("raw_results = parallel_executor")
    assert description_save < resource_search

    code_blocks = re.findall(r"<code>\n(.*?)\n</code>", prompt, re.DOTALL)
    assert len(code_blocks) == 7
    for code_block in code_blocks:
        ast.parse(code_block)

    few_shots_save = next(
        code_block
        for code_block in code_blocks
        if 'fields={"few_shots_prompt": few_shots}' in code_block
    )
    assert r"\x3ccode>" in few_shots_save
    assert r"\x3c/code>" in few_shots_save
    assert r"Observation\x3a" not in few_shots_save
    assert "<code>" not in few_shots_save
    assert "</code>" not in few_shots_save
    assert "Observation:" not in few_shots_save

    few_shots_assignment = ast.parse(few_shots_save).body[0]
    assert isinstance(few_shots_assignment, ast.Assign)
    stored_few_shots = ast.literal_eval(few_shots_assignment.value)
    assert "<code>" in stored_few_shots
    assert "</code>" in stored_few_shots
    assert "Observation:" not in stored_few_shots
    if language == "en":
        assert "The system supplies the tool result in subsequent context" in stored_few_shots
    else:
        assert "系统在后续上下文中提供工具结果" in stored_few_shots


def test_build_nl2agent_system_prompt_falls_back_to_chinese():
    assert build_nl2agent_system_prompt("fr") == build_nl2agent_system_prompt("zh")


@pytest.mark.parametrize(
    (
        "language",
        "boundary_heading",
        "deferred_rule",
        "resource_rule",
        "empty_resource_rule",
        "single_invocation_rule",
        "summary_rule",
    ),
    [
        (
            "en",
            "### Scheduled-task Boundary",
            "this workflow does not create the scheduled task",
            "Never search for a scheduled-task resource",
            'resource_result={"status": "success", "resources": []}',
            "Every Prompt field describes one invocation",
            "open [Scheduled tasks](/agent-tasks)",
        ),
        (
            "zh",
            "### 定时任务边界",
            "本流程不创建定时任务",
            "不得搜索定时任务资源",
            'resource_result={"status": "success", "resources": []}',
            "所有 Prompt 字段只描述 Agent 单次被调用时的行为",
            "前往[定时任务](/agent-tasks)",
        ),
    ],
)
def test_build_nl2agent_system_prompt_defers_scheduled_tasks_until_agent_chat(
    language,
    boundary_heading,
    deferred_rule,
    resource_rule,
    empty_resource_rule,
    single_invocation_rule,
    summary_rule,
):
    prompt = build_nl2agent_system_prompt(language)

    assert boundary_heading in prompt
    assert deferred_rule in prompt
    assert resource_rule in prompt
    assert empty_resource_rule in prompt
    assert single_invocation_rule in prompt
    assert summary_rule in prompt
    assert prompt.count("(/agent-tasks)") == 1


@pytest.mark.parametrize(
    (
        "language",
        "priority_heading",
        "state_rule",
        "linear_priority_rule",
        "partial_patch_rule",
        "preserve_rule",
        "clarification_rule",
        "resource_scope_rule",
        "reconfigure_rule",
        "resource_continue_rule",
        "revision_summary_rule",
        "removal_rule",
        "immutable_boundary",
    ),
    [
        (
            "en",
            "### Revision Mode Priority",
            "Determine completion from the current `nl2agent_verified_state`",
            "always take priority over the linear generation state machine",
            "One request may update multiple explicitly requested fields in one save call",
            "Omit every unspecified field so its persisted value remains unchanged",
            "listing only the potentially affected fields",
            "searches only for the newly requested capability",
            "reconfigure a specifically requested bound resource",
            "Never start at `duty_prompt` or enter the full Prompt generation chain",
            'Start with "Updated:"',
            "Conversational removal is unsupported",
            "model settings, publication status, version state",
        ),
        (
            "zh",
            "### 修订模式优先级",
            "只能根据当前 `nl2agent_verified_state` 判断是否完成",
            "始终优先于线性生成状态机",
            "一次请求可在一次保存调用中更新多个明确指定字段",
            "所有未指定字段都必须省略并保持数据库原值",
            "只列出可能受影响的字段",
            "只搜索用户新请求的能力",
            "重新配置用户明确指定的已绑定资源",
            "不得因卡片已确认就从 `duty_prompt` 开始",
            "以“已更新：”开头",
            "不支持通过对话移除资源",
            "模型设置、发布状态、版本状态",
        ),
    ],
)
def test_build_nl2agent_system_prompt_prioritizes_completed_draft_revisions(
    language,
    priority_heading,
    state_rule,
    linear_priority_rule,
    partial_patch_rule,
    preserve_rule,
    clarification_rule,
    resource_scope_rule,
    reconfigure_rule,
    resource_continue_rule,
    revision_summary_rule,
    removal_rule,
    immutable_boundary,
):
    prompt = build_nl2agent_system_prompt(language)

    assert "### Intent And Minimal Workflow" in prompt or "### 任务意图与最小流程" in prompt
    assert "Partial tasks are exempt" in prompt or "局部任务不受此规则影响" in prompt
    assert partial_patch_rule in prompt
    assert preserve_rule in prompt
    assert clarification_rule in prompt
    assert "Never cascade automatically" in prompt or "禁止自动级联" in prompt
    assert resource_scope_rule in prompt
    assert (
        "does not confirm any Prompt update" in prompt
        or "不代表用户确认更新任何 Prompt" in prompt
    )
    assert reconfigure_rule in prompt
    assert "resource-dependent" in prompt.lower() or "资源依赖" in prompt
    assert revision_summary_rule in prompt
    assert removal_rule in prompt
    assert immutable_boundary in prompt
    assert "Resource-Dependent Prompt Generation" in prompt or "资源依赖 Prompt 生成" in prompt
    assert "updated_fields" in prompt


@pytest.mark.parametrize("language", ["zh", "en"])
def test_build_nl2agent_system_prompt_uses_mounted_tool_names(language):
    prompt = build_nl2agent_system_prompt(language)

    assert f"({SEARCH_INSTALLED_RESOURCES_NAME}," in prompt
    assert f"({SEARCH_UNINSTALLED_RESOURCES_NAME}," in prompt
    assert f"raw_resource_result = {RECOMMEND_RESOURCES_NAME}(" in prompt
    assert f"saved = {SAVE_AGENT_DRAFT_FIELDS_NAME}(" in prompt
    assert f"wrapped = {NL2A_WRAPPER_NAME}(" in prompt
    assert "external_registry" not in prompt
    assert "MCP_OFFICIAL_REGISTRY" not in prompt


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

    empty_wrapped = build_nl2a_wrapper(
        subtype="installed_resource_binding",
        agent_id=42,
        resource_result={"status": "success", "resources": []},
    )
    empty_payload = json.loads(
        empty_wrapped.split("<nl2a>", 1)[1].split("</nl2a>", 1)[0]
    )
    assert empty_payload == {
        "subtype": "installed_resource_binding",
        "agent_id": 42,
        "resources": [],
    }


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
        SEARCH_UNINSTALLED_RESOURCES_NAME,
        RECOMMEND_RESOURCES_NAME,
        SAVE_AGENT_DRAFT_FIELDS_NAME,
        NL2A_WRAPPER_NAME,
        ParallelExecutorTool.name,
    ]
    assert [tool.description for tool in config.tools] == [
        registered_tools[SEARCH_INSTALLED_RESOURCES_NAME].description,
        registered_tools[SEARCH_UNINSTALLED_RESOURCES_NAME].description,
        registered_tools[RECOMMEND_RESOURCES_NAME].description,
        registered_tools[SAVE_AGENT_DRAFT_FIELDS_NAME].description,
        registered_tools[NL2A_WRAPPER_NAME].description,
        ParallelExecutorTool.description,
    ]
    assert json.loads(config.tools[0].inputs)["agent_id"] == "int"
    assert json.loads(config.tools[1].inputs)["agent_id"] == "int"
    assert json.loads(config.tools[2].inputs)["agent_id"] == "int"
    save_inputs = json.loads(config.tools[3].inputs)
    assert save_inputs["agent_id"] == "int"
    assert set(save_inputs["fields"]) == {
        "description",
        "duty_prompt",
        "constraint_prompt",
        "few_shots_prompt",
        "greeting_message",
        "example_questions",
    }
    assert set(json.loads(config.tools[4].inputs)) == {
        "subtype",
        "agent_id",
        "resource_result",
        "questions",
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
    assert "当 `description` 缺失、为空字符串或只包含空白时，该草稿是“空描述草稿”" in message_texts[0]
    assert message_texts[1] == "Verified database binding facts: agent_id=42"
    assert message_texts[2] == "配置这个草稿"


def test_agent_draft_fields_rejects_removed_business_description():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AgentDraftFields(
            description="Research help",
            business_description="Verify and summarize sources",
        )
