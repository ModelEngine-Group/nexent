import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from services.agent_automation.intent_analyzer import (
    AutomationIntentContext,
    AutomationIntentStrategyFactory,
    LLMAutomationIntentStrategy,
    RuleBasedAutomationIntentStrategy,
)


REFERENCE_TIME = datetime(2026, 7, 13, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
MODEL_CONFIG = {
    "model_name": "test-model",
    "model_repo": "",
    "model_type": "llm",
}


class _StubLLMStrategy(LLMAutomationIntentStrategy):
    def __init__(self, response):
        super().__init__(MODEL_CONFIG, RuleBasedAutomationIntentStrategy())
        self.response = response
        self.calls = 0

    def _generate_sync(self, context):
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _context(message: str) -> AutomationIntentContext:
    return AutomationIntentContext(
        tenant_id="tenant",
        message=message,
        timezone="Asia/Shanghai",
        reference_time=REFERENCE_TIME,
    )


@pytest.mark.asyncio
async def test_llm_analyzer_generates_task_content_and_valid_cron_in_one_call():
    strategy = _StubLLMStrategy(json.dumps({
        "is_automation_intent": True,
        "confidence": 0.99,
        "title": "查询黄历",
        "instruction": "查询当天的黄历信息",
        "schedule": {
            "rule_type": "CRON",
            "timezone": "Asia/Shanghai",
            "cron_expr": "0 8 * * *",
            "interval_seconds": None,
            "start_at": None,
            "end_at": None,
            "max_fire_count": None,
        },
        "schedule_error": None,
    }, ensure_ascii=False))

    result = await strategy.analyze(_context("每天早上八点算一下当天的黄历信息"))

    assert strategy.calls == 1
    assert result["is_automation_intent"] is True
    assert result["analysis_source"] == "llm"
    assert result["task_content_generated"] is True
    assert result["task_content_source"] == "llm"
    assert result["title"] == "查询黄历"
    assert result["instruction"] == "查询当天的黄历信息"
    assert result["schedule_trigger"].cron_expr == "0 8 * * *"


@pytest.mark.asyncio
async def test_llm_analyzer_distinguishes_ordinary_time_related_task():
    strategy = _StubLLMStrategy(json.dumps({
        "is_automation_intent": False,
        "confidence": 0.97,
        "title": "",
        "instruction": "",
        "schedule": None,
        "schedule_error": None,
    }))

    result = await strategy.analyze(_context("帮我分析一下每天早上八点的销量"))

    assert strategy.calls == 1
    assert result == {
        "is_automation_intent": False,
        "confidence": 0.97,
        "analysis_source": "llm",
    }


@pytest.mark.asyncio
async def test_llm_analyzer_builds_interval_trigger_without_model_date_arithmetic():
    strategy = _StubLLMStrategy(json.dumps({
        "is_automation_intent": True,
        "confidence": 0.98,
        "title": "检查服务",
        "instruction": "检查服务状态",
        "schedule": {
            "rule_type": "INTERVAL",
            "timezone": "Asia/Shanghai",
            "cron_expr": None,
            "interval_seconds": 300,
            "start_at": None,
            "end_at": None,
            "max_fire_count": None,
        },
        "schedule_error": None,
    }, ensure_ascii=False))

    result = await strategy.analyze(_context("每五分钟检查服务状态"))

    trigger = result["schedule_trigger"]
    assert trigger.interval_seconds == 300
    assert trigger.start_at == datetime(2026, 7, 13, 10, 5, tzinfo=ZoneInfo("Asia/Shanghai"))


@pytest.mark.asyncio
async def test_llm_analyzer_rejects_invalid_cron_without_running_as_ordinary_chat():
    strategy = _StubLLMStrategy(json.dumps({
        "is_automation_intent": True,
        "confidence": 0.95,
        "title": "检查状态",
        "instruction": "检查服务状态",
        "schedule": {
            "rule_type": "CRON",
            "timezone": "Asia/Shanghai",
            "cron_expr": "61 25 * * *",
            "interval_seconds": None,
            "start_at": None,
            "end_at": None,
            "max_fire_count": None,
        },
        "schedule_error": None,
    }, ensure_ascii=False))

    result = await strategy.analyze(_context("每天早上八点检查服务状态"))

    assert result["is_automation_intent"] is True
    assert result["schedule_trigger"] is None
    assert "Cron" in result["schedule_error"]


@pytest.mark.asyncio
async def test_llm_analyzer_falls_back_to_rules_when_model_output_is_unusable():
    strategy = _StubLLMStrategy("not-json")

    result = await strategy.analyze(_context("每天早上八点检查服务状态"))

    assert result["analysis_source"] == "rule"
    assert result["schedule_trigger"].cron_expr == "0 8 * * *"


@pytest.mark.asyncio
async def test_llm_analyzer_skips_model_when_message_has_no_schedule_signal():
    strategy = _StubLLMStrategy(AssertionError("model must not be called"))

    result = await strategy.analyze(_context("帮我总结一下项目进展"))

    assert strategy.calls == 0
    assert result["is_automation_intent"] is False
    assert result["analysis_source"] == "rule"


def test_strategy_factory_prefers_selected_llm_model(monkeypatch):
    captured = []

    def fake_get_model_by_id(model_id, tenant_id):
        captured.append((model_id, tenant_id))
        return MODEL_CONFIG

    monkeypatch.setattr(
        "services.agent_automation.intent_analyzer.get_model_by_model_id",
        fake_get_model_by_id,
    )
    context = AutomationIntentContext(
        tenant_id="tenant",
        message="每天八点检查状态",
        model_id=42,
    )

    strategy = AutomationIntentStrategyFactory().create(context)

    assert isinstance(strategy, LLMAutomationIntentStrategy)
    assert captured == [(42, "tenant")]
