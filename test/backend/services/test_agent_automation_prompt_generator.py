from types import SimpleNamespace

import pytest

from services.agent_automation import prompt_generator
from services.agent_automation.prompt_generator import (
    AutomationPromptStrategy,
    AutomationPromptStrategyFactory,
    AutomationPromptContext,
    AutomationPromptGenerator,
    AutomationTaskContent,
    LLMAutomationPromptStrategy,
    TemplateAutomationPromptStrategy,
    _extract_json,
    detect_instruction_language,
    _normalize_model_output,
    _normalize_task_content,
)


def test_detect_instruction_language_keeps_english_tasks_on_english_prompt():
    assert detect_instruction_language("send a status report") == "en"
    assert detect_instruction_language("生成 Excel 报告") == "zh"


@pytest.mark.asyncio
async def test_english_fallback_title_is_not_truncated_to_chinese_limit():
    instruction = "send a comprehensive weekly project status report"
    content = await TemplateAutomationPromptStrategy().generate_task_content(
        AutomationPromptContext(
            tenant_id="tenant",
            instruction=instruction,
            language="en",
        )
    )

    assert content.title == instruction


@pytest.mark.asyncio
async def test_template_strategy_keeps_instruction_direct():
    strategy = TemplateAutomationPromptStrategy()

    result = await strategy.generate_task_content(AutomationPromptContext(
        tenant_id="tenant",
        instruction="发一个周报",
    ))

    assert result.instruction == "发一个周报"
    assert result.title == "发送周报"


@pytest.mark.asyncio
async def test_template_strategy_generates_concise_reminder_title():
    content = await TemplateAutomationPromptStrategy().generate_task_content(
        AutomationPromptContext(
            tenant_id="tenant",
            instruction="提醒我提交周报",
        )
    )

    assert content == AutomationTaskContent(
        title="提交周报提醒",
        instruction="提醒我提交周报",
    )


@pytest.mark.asyncio
async def test_template_strategy_normalizes_colloquial_action_in_title_only():
    content = await TemplateAutomationPromptStrategy().generate_task_content(
        AutomationPromptContext(
            tenant_id="tenant",
            instruction="算一下当天的黄历信息",
        )
    )

    assert content == AutomationTaskContent(
        title="计算当天的黄历信息",
        instruction="算一下当天的黄历信息",
    )


@pytest.mark.asyncio
async def test_template_strategy_generates_stable_title_and_instruction():
    content = await TemplateAutomationPromptStrategy().generate_task_content(AutomationPromptContext(
        tenant_id="tenant",
        instruction="汇总销售数据并生成 Excel 表格",
    ))

    assert content == AutomationTaskContent(
        title="汇总销售数据并生成 Excel 表格",
        instruction="汇总销售数据并生成 Excel 表格",
    )


def test_structured_task_content_keeps_only_title_and_business_instruction():
    content = _normalize_task_content(
        '{"title":"发送你好","instruction":"发送一次“你好”"}',
        AutomationTaskContent(title="发一句你好", instruction="发一句你好"),
        source="发一句你好",
    )

    assert content.title == "发送你好"
    assert content.instruction == "发送一次“你好”"


def test_structured_task_content_rejects_orchestration_noise():
    content = _normalize_task_content(
        '{"title":"定时问候任务","instruction":"使用 Agent 工具创建定时任务并发送你好"}',
        AutomationTaskContent(title="发送你好", instruction="发送一次“你好”"),
        source="发一句你好",
    )

    assert content == AutomationTaskContent(title="发送你好", instruction="发送一次“你好”")


def test_structured_task_content_rejects_reintroduced_schedule_noise():
    fallback = AutomationTaskContent(title="发送你好", instruction="发送一次“你好”")
    content = _normalize_task_content(
        '{"title":"每日问候","instruction":"每天9点发送一次你好"}',
        fallback,
        source="发送一次你好",
    )

    assert content == fallback


def test_structured_task_content_rejects_extra_json_fields():
    fallback = AutomationTaskContent(title="发送你好", instruction="发送一次“你好”")
    content = _normalize_task_content(
        '{"title":"发送你好","instruction":"发送一次你好","cron":"0 9 * * *"}',
        fallback,
        source="发送一次你好",
    )

    assert content == fallback


def test_structured_task_content_rejects_language_translation():
    fallback = AutomationTaskContent(title="发送你好", instruction="发送一次你好")
    content = _normalize_task_content(
        '{"title":"Send hello","instruction":"Send hello once"}',
        fallback,
        source="发送一次你好",
    )

    assert content == fallback


def test_model_output_with_added_orchestration_details_falls_back_to_direct_instruction():
    result = _normalize_model_output(
        "根据 Agent hello_assistant 的能力创建定时任务，"
        "并使用工具发送你好，失败后重试一次。",
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
async def test_generator_delegates_to_factory_for_creation_time_content():
    calls = []

    class _Strategy(TemplateAutomationPromptStrategy):
        async def generate_task_content(self, context):
            calls.append(context.instruction)
            return AutomationTaskContent(title="整理周报", instruction=f"optimized:{context.instruction}")

    class _Factory:
        def create(self, tenant_id):
            return _Strategy()

    generator = AutomationPromptGenerator(factory=_Factory())
    context = AutomationPromptContext(
        tenant_id="tenant",
        instruction="整理周报",
    )

    first = await generator.generate_task_content(context)
    second = await generator.generate_task_content(context)

    assert first == second == AutomationTaskContent(title="整理周报", instruction="optimized:整理周报")
    assert len(calls) == 2


def test_model_and_json_normalizers_cover_empty_fenced_and_embedded_content():
    assert _normalize_model_output("", "fallback", 10) == "fallback"
    assert _extract_json('```json\n{"title":"A","instruction":"B"}\n```') == {
        "title": "A",
        "instruction": "B",
    }
    assert _extract_json('prefix {"title":"A","instruction":"B"} suffix')["title"] == "A"
    with pytest.raises(ValueError, match="JSON object"):
        _extract_json('["not", "an", "object"]')
    with pytest.raises(ValueError):
        _extract_json("not json")


def test_structured_task_content_rejects_invalid_or_translated_title():
    fallback = AutomationTaskContent(title="发送你好", instruction="发送一次你好")
    assert _normalize_task_content(
        '{"title":"定时任务","instruction":"发送一次你好"}',
        fallback,
        source="发送一次你好",
    ) == fallback
    assert _normalize_task_content(
        '{"title":"Hello","instruction":"发送一次你好"}',
        fallback,
        source="发送一次你好",
    ) == fallback


@pytest.mark.asyncio
async def test_abstract_and_llm_strategies_cover_success_and_fail_open(monkeypatch):
    context = AutomationPromptContext(tenant_id="tenant", instruction="发送一次你好")
    with pytest.raises(NotImplementedError):
        await AutomationPromptStrategy.generate_task_content(object(), context)

    fallback = TemplateAutomationPromptStrategy()
    strategy = LLMAutomationPromptStrategy({"model_name": "model"}, fallback)
    monkeypatch.setattr(
        strategy,
        "_generate_sync",
        lambda *args: '{"title":"发送你好","instruction":"发送一次你好"}',
    )
    assert await strategy.generate_task_content(context) == AutomationTaskContent(
        title="发送你好",
        instruction="发送一次你好",
    )

    monkeypatch.setattr(
        strategy,
        "_generate_sync",
        lambda *args: (_ for _ in ()).throw(RuntimeError("model unavailable")),
    )
    assert await strategy.generate_task_content(context) == AutomationTaskContent(
        title="发送你好",
        instruction="发送一次你好",
    )


def test_llm_strategy_builds_model_request_from_tenant_configuration(monkeypatch):
    captured = {}

    class FakeModel:
        def __init__(self, **kwargs):
            captured["config"] = kwargs

        def generate(self, messages):
            captured["messages"] = messages
            return SimpleNamespace(content='{"title":"A","instruction":"B"}')

    monkeypatch.setattr("nexent.core.models.OpenAIModel", FakeModel)
    monkeypatch.setattr("utils.config_utils.get_model_name_from_config", lambda config: "resolved-model")
    monkeypatch.setattr(
        prompt_generator,
        "get_prompt_template",
        lambda name, language: {
            "TASK_CONTENT_SYSTEM_PROMPT": "system",
            "TASK_CONTENT_USER_PROMPT": "Instruction: {{ instruction }}",
        },
    )
    strategy = LLMAutomationPromptStrategy(
        {
            "model_name": "configured",
            "base_url": "https://example.com",
            "api_key": "secret",
            "model_factory": "openai",
            "ssl_verify": False,
            "timeout_seconds": 10,
        },
        TemplateAutomationPromptStrategy(),
    )

    result = strategy._generate_sync(
        AutomationPromptContext(tenant_id="tenant", instruction="  do work  ", language="en"),
        "TASK_CONTENT_SYSTEM_PROMPT",
        "TASK_CONTENT_USER_PROMPT",
    )

    assert result == '{"title":"A","instruction":"B"}'
    assert captured["config"]["model_id"] == "resolved-model"
    assert captured["config"]["ssl_verify"] is False
    assert captured["messages"][1]["content"] == "Instruction: do work"


def test_prompt_strategy_factory_selects_llm_and_falls_back_on_config_error(monkeypatch):
    factory = AutomationPromptStrategyFactory()
    monkeypatch.setattr(
        "utils.config_utils.tenant_config_manager.get_model_config",
        lambda **kwargs: {"model_name": "configured"},
    )
    assert isinstance(factory.create("tenant"), LLMAutomationPromptStrategy)

    monkeypatch.setattr(
        "utils.config_utils.tenant_config_manager.get_model_config",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("config unavailable")),
    )
    assert isinstance(factory.create("tenant"), TemplateAutomationPromptStrategy)
