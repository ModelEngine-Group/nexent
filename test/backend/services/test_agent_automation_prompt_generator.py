from datetime import datetime, timezone

import pytest

from services.agent_automation.prompt_generator import (
    AutomationPromptContext,
    AutomationPromptGenerator,
    LLMAutomationPromptStrategy,
    TemplateAutomationPromptStrategy,
    _normalize_model_output,
)


@pytest.mark.asyncio
async def test_template_strategy_keeps_instruction_direct():
    strategy = TemplateAutomationPromptStrategy()

    result = await strategy.optimize_instruction(AutomationPromptContext(
        tenant_id="tenant",
        instruction="发一个周报",
        agent_snapshot={"agent_id": 7, "name": "周报助手", "description": "整理项目进展"},
        capability_bindings=[{"type": "KNOWLEDGE_BASE", "display_name": "项目资料"}],
    ))

    assert result == "发一个周报"


@pytest.mark.asyncio
async def test_llm_strategy_reuses_confirmed_instruction_for_execution():
    fallback = TemplateAutomationPromptStrategy()
    strategy = LLMAutomationPromptStrategy({"model_name": "unused"}, fallback)

    result = await strategy.generate_execution_prompt(AutomationPromptContext(
        tenant_id="tenant",
        instruction="发送一次“你好”",
        agent_snapshot={"name": "hello_assistant"},
        scheduled_fire_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        trigger_type="MANUAL",
    ))

    assert result == "发送一次“你好”"


def test_model_output_with_added_orchestration_details_falls_back_to_direct_instruction():
    result = _normalize_model_output(
        "根据 Agent hello_assistant 的能力创建定时任务，并使用工具发送你好，失败后重试一次。",
        "发送一次“你好”",
        300,
        source="发你好",
    )

    assert result == "发送一次“你好”"


def test_model_output_keeps_orchestration_word_when_user_requested_it():
    result = _normalize_model_output(
        "检查 Agent 工具状态",
        "检查 Agent 工具",
        300,
        source="检查 Agent 工具",
    )

    assert result == "检查 Agent 工具状态"


def test_overlong_model_output_falls_back_without_truncating_the_task():
    result = _normalize_model_output(
        "生成周报" * 100,
        "生成周报",
        300,
        source="生成周报",
    )

    assert result == "生成周报"


@pytest.mark.asyncio
async def test_generator_delegates_to_factory_strategy_for_every_run():
    calls = []

    class _Strategy(TemplateAutomationPromptStrategy):
        async def generate_execution_prompt(self, context):
            calls.append(context.scheduled_fire_at)
            return f"optimized:{context.instruction}"

    class _Factory:
        def create(self, tenant_id):
            return _Strategy()

    generator = AutomationPromptGenerator(factory=_Factory())
    context = AutomationPromptContext(
        tenant_id="tenant",
        instruction="整理周报",
        scheduled_fire_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )

    first = await generator.generate_execution_prompt(context)
    second = await generator.generate_execution_prompt(context)

    assert first == second == "optimized:整理周报"
    assert len(calls) == 2
