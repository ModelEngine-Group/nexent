# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from jinja2 import UndefinedError
from nexent.core.agents.context import ContextItemInput, ContextManager, ContextManagerConfig
from nexent.core.tools.parallel_executor import ParallelExecutorTool
from pydantic import ValidationError
from smolagents import CodeAgent
from smolagents.memory import TaskStep

from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent.nl2agent_tools import (
    AgentDraftFields,
    DISCOVER_REQUIREMENTS_NAME,
    VERIFY_REQUIREMENTS_NAME,
    SHOW_RESOURCE_CARD_NAME,
    READ_CONFIGURATION_NAME,
    SAVE_CONFIGURATION_NAME,
    READ_GENERATION_CONTEXT_NAME,
    NL2A_WRAPPER_NAME,
    RECOMMEND_RESOURCES_NAME,
    RecommendResourcesInput,
    RequirementClarificationPayload,
    ResourceCandidate,
    ResourceRequirement,
    SAVE_AGENT_DRAFT_FIELDS_NAME,
    VALIDATE_AGENT_GENERATION_COMPLETE_NAME,
    SEARCH_INSTALLED_RESOURCES_NAME,
    SEARCH_UNINSTALLED_RESOURCES_NAME,
    SearchInstalledResourcesInput,
    build_nl2a_wrapper,
)
from runtime.agentos.agent_creator_config import (
    build_nl2agent_system_prompt,
    create_nl2agent_agent_config,
)
from runtime.agentos.prepared_agent_creator import _callback_tools
from tool_collection.mcp.local_mcp_service import local_mcp_service


@pytest.mark.parametrize(
    ("language", "heading", "name_rule", "description_rule"),
    [
        (
            "en",
            "### Role",
            "When `name` is absent, empty, or whitespace-only",
            "Save the description once the purpose is clear",
        ),
        (
            "zh",
            "### 核心职责",
            "当 `name` 缺失、为空字符串或只包含空白时",
            "目标明确后保存描述",
        ),
    ],
)
def test_build_nl2agent_system_prompt_configures_existing_draft(
    language,
    heading,
    name_rule,
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
    assert name_rule in prompt
    assert description_rule in prompt
    assert DISCOVER_REQUIREMENTS_NAME in prompt
    assert VERIFY_REQUIREMENTS_NAME in prompt
    assert "runtime_wrapper" in prompt
    assert "runtime_save" in prompt
    assert "JSON" in prompt
    assert "bound_resources" in prompt
    assert "business_description" not in prompt
    assert "requirement_clarification" in prompt
    assert SHOW_RESOURCE_CARD_NAME in prompt
    assert 'subtype="final_confirmation"' not in prompt
    assert "agent_generation_completed" in prompt
    assert "agent_id=None" not in prompt
    assert "nl2agent_tool_selection" not in prompt
    assert 'subtype="agent_draft"' not in prompt
    assert 'subtype="local_mcp_recommendation"' not in prompt
    assert "<nl2a>" not in prompt
    assert "```" not in prompt

    if language == "en":
        assert "Enter Resource-Dependent Prompt Generation for actual resource changes" in prompt
        assert "atomically save the complete Prompt using the verified resources and declared inputs" in prompt
        assert "### State And Completion Rules" in prompt
        assert "They never prove that its configuration is complete" in prompt
        assert "clarify with one requirement_clarification card" in prompt
        assert "Partial tasks are exempt" in prompt
        assert "Configuration is complete only after the description is saved" in prompt
        assert "Before the validation tool succeeds" in prompt
        assert "purpose=\"recommend\" for recommendations only" in prompt
        assert "### Completion Summary" in prompt
        assert "New Agent summary:" in prompt
        assert "### Atomic Action Contract" in prompt
        assert "once the action is known, submit it immediately" in prompt
        assert 'equal to `["prompt"]`' in prompt
        assert "Core-neutral example" in prompt
        assert "Weather Assistant" not in prompt
        assert "Describe the tasks this Agent must perform" not in prompt
    else:
        assert "资源依赖 Prompt 生成" in prompt
        assert "修订总结" in prompt
        assert "### 状态判定与完成标准" in prompt
        assert "不证明该 Agent 已完成配置" in prompt
        assert "如果目标、预期结果或关键约束不明确，使用一张需求澄清卡" in prompt
        assert "局部任务不受此规则影响" in prompt
        assert "只有描述已保存、资源需求已安装并绑定或明确放弃" in prompt
        assert "显式校验工具成功前，不得声称完整生成已完成" in prompt
        assert '只推荐用 purpose="recommend"' in prompt
        assert "### 完成总结" in prompt
        assert "新智能体已完成生成" in prompt
        assert "### 原子动作输出契约" in prompt
        assert "确定动作后必须立即提交该动作" in prompt
        assert '`updated_fields` 是 `["prompt"]`' in prompt
        assert "写一个 Core 中立的使用示例" in prompt
        assert "天气助手" not in prompt
        assert "请详细说明这个智能体需要完成的任务" not in prompt

    assert not any(marker in prompt for marker in ("<code>", "<final_answer>", "print(", "nexent_execute_python"))


def test_build_nl2agent_system_prompt_falls_back_to_chinese():
    assert build_nl2agent_system_prompt("fr") == build_nl2agent_system_prompt("zh")


@pytest.mark.parametrize(
    ("language", "skip_all_rule"),
    [
        (
            "en",
            "If there are no resource requirements, go directly to Prompt generation",
        ),
        ("zh", "没有资源需求时直接生成 Prompt"),
    ],
)
def test_build_nl2agent_system_prompt_handles_creation_without_resources(
    language,
    skip_all_rule,
):
    prompt = build_nl2agent_system_prompt(language)

    assert skip_all_rule in prompt
    assert "nl2a_read_generation_context" in prompt


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
            "If there are no resource requirements, go directly to Prompt generation",
            "Every Prompt field describes one invocation",
            "open [Scheduled tasks](/agent-tasks)",
        ),
        (
            "zh",
            "### 定时任务边界",
            "本流程不创建定时任务",
            "不得搜索定时任务资源",
            "没有资源需求时直接生成 Prompt",
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
            'purpose="bind" to add resources',
            "An accepted continue action uses confirmed_requirements from the trusted context and the saved bound_resources",
            "Never start at `prompt` or enter the full Prompt generation chain",
            'Start with "Updated:"',
            "If the user asks to remove a resource",
            "names, icons, inference parameters",
        ),
        (
            "zh",
            "### 修订模式优先级",
            "只能根据当前 `nl2agent_verified_state` 判断是否完成",
            "始终优先于线性生成状态机",
            "一次请求可在一次保存调用中更新多个明确指定字段",
            "所有未指定字段都必须省略并保持数据库原值",
            "只列出可能受影响的字段",
            '新增资源用 purpose="bind"',
            "运行服务接受 continue 后",
            "不得因卡片已确认就从 `prompt` 开始",
            "以“已更新：”开头",
            "用户要求移除资源时",
            "名称、头像、推理参数",
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

    assert "### Understand the user's goal" in prompt or "### 明确用户要做什么" in prompt
    assert "Partial tasks are exempt" in prompt or "局部任务不受此规则影响" in prompt
    assert partial_patch_rule in prompt
    assert preserve_rule in prompt
    assert clarification_rule in prompt
    assert "Never cascade automatically" in prompt or "禁止自动级联" in prompt
    assert resource_scope_rule in prompt
    assert "nl2a_read_agent_configuration" in prompt
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

    assert DISCOVER_REQUIREMENTS_NAME in prompt
    assert VERIFY_REQUIREMENTS_NAME in prompt
    assert "requirements_limit_exceeded" in prompt
    assert "max_requirements" in prompt
    assert ("split the request" if language == "en" else "分批或缩小范围") in prompt
    assert SHOW_RESOURCE_CARD_NAME in prompt
    assert SAVE_AGENT_DRAFT_FIELDS_NAME in prompt
    assert VALIDATE_AGENT_GENERATION_COMPLETE_NAME in prompt
    assert NL2A_WRAPPER_NAME in prompt
    assert "external_registry" not in prompt
    assert "MCP_OFFICIAL_REGISTRY" not in prompt


def test_build_nl2agent_system_prompt_rejects_unknown_template_variables(mocker):
    prompt_loader = mocker.patch(
        "nexent.core.agents.prompt.meta.load_prompt",
        return_value={"system_prompt": "{{ missing_value }}"},
    )

    with pytest.raises(UndefinedError, match="missing_value"):
        build_nl2agent_system_prompt("en")

    prompt_loader.assert_called_once_with("en", "meta/nl2agent")


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
    empty_payload = json.loads(empty_wrapped)
    assert empty_payload == {
        "status": "success",
        "subtype": "installed_resource_binding",
        "agent_id": 42,
        "binding_required": False,
        "resources": [],
    }
    assert "<nl2a>" not in empty_wrapped


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


@pytest.mark.parametrize("configured_steps, expected_steps", [(None, 15), (8, 15), (20, 20)])
def test_create_nl2agent_config_leaves_room_for_multi_step_verification(configured_steps, expected_steps):
    snapshot = None if configured_steps is None else {
        "agent_id": 42, "version_no": 0, "description": "Creator", "max_steps": configured_steps,
    }
    config = create_nl2agent_agent_config("zh", [], snapshot=snapshot)
    assert config.max_steps == expected_steps


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["zh", "en"])
async def test_create_nl2agent_agent_config_has_only_current_runtime_tools(language):
    """UT-BE-DPR-011: ephemeral agents retain parallel tool localization."""
    actor = ServicePrincipal("user", "tenant")
    tools = list(_callback_tools(SimpleNamespace(run_id="a" * 32, agent_id=42), actor))
    config = create_nl2agent_agent_config(language, tools)
    assert all(tool.source == "langchain" for tool in config.tools[:-1])
    registered_tools = await local_mcp_service.get_tools()

    assert [tool.name for tool in config.tools] == [
        DISCOVER_REQUIREMENTS_NAME,
        VERIFY_REQUIREMENTS_NAME,
        SHOW_RESOURCE_CARD_NAME,
        READ_CONFIGURATION_NAME,
        SAVE_CONFIGURATION_NAME,
        READ_GENERATION_CONTEXT_NAME,
        SEARCH_INSTALLED_RESOURCES_NAME,
        SEARCH_UNINSTALLED_RESOURCES_NAME,
        RECOMMEND_RESOURCES_NAME,
        SAVE_AGENT_DRAFT_FIELDS_NAME,
        VALIDATE_AGENT_GENERATION_COMPLETE_NAME,
        NL2A_WRAPPER_NAME,
        ParallelExecutorTool.name,
    ]
    assert [tool.description for tool in config.tools[:-1]] == [
        registered_tools[tool.name].description for tool in config.tools[:-1]
    ]
    assert config.tools[-1].description == ParallelExecutorTool.description
    assert config.tools[-1].description_zh == ParallelExecutorTool.description_zh
    inputs_by_tool = {tool.name: json.loads(tool.inputs) for tool in config.tools}
    assert inputs_by_tool[SEARCH_INSTALLED_RESOURCES_NAME]["agent_id"] == "int"
    assert inputs_by_tool[SEARCH_UNINSTALLED_RESOURCES_NAME]["agent_id"] == "int"
    assert inputs_by_tool[RECOMMEND_RESOURCES_NAME]["agent_id"] == "int"
    assert "agent_id" not in inputs_by_tool[DISCOVER_REQUIREMENTS_NAME]
    assert "agent_id" not in inputs_by_tool[SAVE_CONFIGURATION_NAME]
    save_inputs = inputs_by_tool[SAVE_AGENT_DRAFT_FIELDS_NAME]
    assert save_inputs["agent_id"] == "int"
    assert set(save_inputs["fields"]) == {
        "enable_protocol_repair_retry",
        "name",
        "description",
        "prompt",
        "greeting_message",
        "example_questions",
    }
    assert inputs_by_tool[VALIDATE_AGENT_GENERATION_COMPLETE_NAME] == {}
    assert set(inputs_by_tool[NL2A_WRAPPER_NAME]) == {
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
        "creator_tools": {"save_tool_name": SAVE_AGENT_DRAFT_FIELDS_NAME, "wrapper_name": NL2A_WRAPPER_NAME},
    }
    assert prompt_context.content["text"] == build_nl2agent_system_prompt(language)


def test_nl2agent_explicit_system_context_reaches_final_model_messages():
    config = create_nl2agent_agent_config("zh", [])
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
