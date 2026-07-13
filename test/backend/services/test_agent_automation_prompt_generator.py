from datetime import datetime, timezone

import pytest

from services.agent_automation.prompt_generator import (
    AutomationPromptContext,
    AutomationPromptGenerator,
    TemplateAutomationPromptStrategy,
)


@pytest.mark.asyncio
async def test_template_strategy_builds_agent_aware_instruction():
    strategy = TemplateAutomationPromptStrategy()

    result = await strategy.optimize_instruction(AutomationPromptContext(
        tenant_id="tenant",
        instruction="发一个周报",
        agent_snapshot={"agent_id": 7, "name": "周报助手", "description": "整理项目进展"},
        capability_bindings=[{"type": "KNOWLEDGE_BASE", "display_name": "项目资料"}],
    ))

    assert "周报助手" in result
    assert "整理项目进展" in result
    assert "发一个周报" in result
    assert "当前会话上下文" in result


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
