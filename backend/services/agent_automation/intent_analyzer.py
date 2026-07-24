import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from jinja2 import StrictUndefined, Template
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from consts.const import (
    AGENT_AUTOMATION_MIN_INTERVAL_SECONDS,
    MESSAGE_ROLE,
    MODEL_CONFIG_MAPPING,
)
from database.model_management_db import get_model_by_model_id
from utils.prompt_template_utils import get_prompt_template

from .intent_parser import has_automation_schedule_signal, parse_automation_intent
from .models import ScheduleMode, ScheduleRuleType, ScheduleTrigger
from .prompt_generator import (
    AutomationTaskContent,
    _fallback_title,
    _normalize_task_content,
    detect_instruction_language,
)
from .schedule_engine import is_valid_cron_expression

logger = logging.getLogger("agent_automation.intent_analyzer")


class _LLMSchedulePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_type: ScheduleRuleType
    timezone: Optional[str] = None
    cron_expr: Optional[str] = None
    interval_seconds: Optional[int] = Field(default=None, gt=0)
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    max_fire_count: Optional[int] = Field(default=None, gt=0)


class _LLMIntentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_automation_intent: bool
    confidence: float = Field(ge=0, le=1)
    title: str = ""
    instruction: str = ""
    schedule: Optional[_LLMSchedulePayload] = None
    schedule_error: Optional[str] = None


@dataclass(frozen=True)
class AutomationIntentContext:
    tenant_id: str
    message: str
    timezone: str = "Asia/Shanghai"
    model_id: Optional[int] = None
    reference_time: Optional[datetime] = None


def _analysis_time(context: AutomationIntentContext) -> datetime:
    try:
        zone = ZoneInfo(context.timezone)
    except Exception as exc:
        raise ValueError(f"Invalid automation timezone: {context.timezone}") from exc
    now = context.reference_time or datetime.now(zone)
    return now.astimezone(zone) if now.tzinfo else now.replace(tzinfo=zone)


def _extract_json_object(content: str) -> Dict[str, Any]:
    normalized = re.sub(r"<think>[\s\S]*?</think>", "", content or "", flags=re.IGNORECASE).strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", normalized, flags=re.IGNORECASE)
    if fence_match:
        normalized = fence_match.group(1).strip()
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError:
        object_match = re.search(r"\{[\s\S]*\}", normalized)
        if not object_match:
            raise
        parsed = json.loads(object_match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Automation intent analysis must be a JSON object.")
    return parsed


def _localized_datetime(value: Optional[datetime], zone: ZoneInfo) -> Optional[datetime]:
    if value is None:
        return None
    return value.astimezone(zone) if value.tzinfo else value.replace(tzinfo=zone)


def _invalid_llm_schedule(payload: _LLMIntentPayload, reason: str) -> Dict[str, Any]:
    return {
        "is_automation_intent": True,
        "confidence": payload.confidence,
        "title": payload.title.strip(),
        "instruction": payload.instruction.strip(),
        "schedule_trigger": None,
        "schedule_error": reason,
        "capability_intents": [],
        "output_requirements": {},
        "analysis_source": "llm",
        "task_content_generated": True,
    }


def _payload_to_result(
    payload: _LLMIntentPayload,
    context: AutomationIntentContext,
    fallback: Dict[str, Any],
) -> Dict[str, Any]:
    if not payload.is_automation_intent:
        return {
            "is_automation_intent": False,
            "confidence": payload.confidence,
            "analysis_source": "llm",
        }

    if not payload.instruction.strip():
        return _invalid_llm_schedule(payload, "无法确定自动任务需要执行的具体业务动作。")

    fallback_instruction = (
        fallback.get("instruction")
        if fallback.get("is_automation_intent")
        else payload.instruction.strip()
    ) or context.message.strip()
    fallback_content = AutomationTaskContent(
        title=_fallback_title(fallback_instruction),
        instruction=fallback_instruction,
    )
    task_content = _normalize_task_content(
        json.dumps(
            {"title": payload.title, "instruction": payload.instruction},
            ensure_ascii=False,
        ),
        fallback_content,
        source=fallback_instruction,
    )
    task_content_source = "llm"
    if task_content == fallback_content and (
        payload.title.strip() != fallback_content.title
        or payload.instruction.strip() != fallback_content.instruction
    ):
        task_content_source = "rule"
    if payload.schedule_error:
        invalid = payload.model_copy(update={
            "title": task_content.title,
            "instruction": task_content.instruction,
        })
        return _invalid_llm_schedule(invalid, payload.schedule_error)
    if payload.schedule is None:
        invalid = payload.model_copy(update={
            "title": task_content.title,
            "instruction": task_content.instruction,
        })
        return _invalid_llm_schedule(invalid, "无法确定任务执行时间，请补充具体日期、时间或周期。")

    zone = ZoneInfo(payload.schedule.timezone or context.timezone)
    now = _analysis_time(context).astimezone(zone)
    schedule = payload.schedule
    start_at = _localized_datetime(schedule.start_at, zone)
    end_at = _localized_datetime(schedule.end_at, zone)

    if schedule.rule_type == ScheduleRuleType.AT:
        if start_at is None:
            return _invalid_llm_schedule(payload, "一次性任务缺少明确的未来执行时间。")
        trigger = ScheduleTrigger(
            mode=ScheduleMode.ONCE,
            rule_type=ScheduleRuleType.AT,
            timezone=zone.key,
            start_at=start_at,
            end_at=end_at,
        )
    elif schedule.rule_type == ScheduleRuleType.INTERVAL:
        if schedule.interval_seconds is None:
            return _invalid_llm_schedule(payload, "周期任务缺少有效的执行间隔。")
        if schedule.interval_seconds < AGENT_AUTOMATION_MIN_INTERVAL_SECONDS:
            return _invalid_llm_schedule(
                payload,
                f"任务执行间隔不能小于 {AGENT_AUTOMATION_MIN_INTERVAL_SECONDS} 秒。",
            )
        trigger = ScheduleTrigger(
            mode=ScheduleMode.RECURRING,
            rule_type=ScheduleRuleType.INTERVAL,
            timezone=zone.key,
            start_at=start_at or now.replace(microsecond=0) + timedelta(seconds=schedule.interval_seconds),
            end_at=end_at,
            interval_seconds=schedule.interval_seconds,
            max_fire_count=schedule.max_fire_count,
        )
    else:
        if not schedule.cron_expr or not is_valid_cron_expression(schedule.cron_expr):
            return _invalid_llm_schedule(payload, "大模型生成的 Cron 表达式无效，请补充或修改执行周期。")
        trigger = ScheduleTrigger(
            mode=ScheduleMode.RECURRING,
            rule_type=ScheduleRuleType.CRON,
            timezone=zone.key,
            start_at=start_at or now.replace(second=0, microsecond=0),
            end_at=end_at,
            cron_expr=schedule.cron_expr,
            max_fire_count=schedule.max_fire_count,
        )

    return {
        "is_automation_intent": True,
        "confidence": payload.confidence,
        "title": task_content.title,
        "instruction": task_content.instruction,
        "schedule_trigger": trigger,
        "schedule_error": None,
        "capability_intents": [],
        "output_requirements": {},
        "analysis_source": "llm",
        "task_content_generated": True,
        "task_content_source": task_content_source,
    }


class AutomationIntentAnalysisStrategy(ABC):
    @abstractmethod
    async def analyze(self, context: AutomationIntentContext) -> Dict[str, Any]:
        raise NotImplementedError


class RuleBasedAutomationIntentStrategy(AutomationIntentAnalysisStrategy):
    async def analyze(self, context: AutomationIntentContext) -> Dict[str, Any]:
        result = parse_automation_intent(
            context.message,
            context.timezone,
            context.tenant_id,
            context.reference_time,
        )
        return {
            **result,
            "analysis_source": "rule",
            "task_content_generated": False,
        }


class LLMAutomationIntentStrategy(AutomationIntentAnalysisStrategy):
    def __init__(self, model_config: Dict[str, Any], fallback: AutomationIntentAnalysisStrategy):
        self._model_config = model_config
        self._fallback = fallback

    async def analyze(self, context: AutomationIntentContext) -> Dict[str, Any]:
        fallback = await self._fallback.analyze(context)
        if not has_automation_schedule_signal(context.message):
            return fallback
        try:
            content = await asyncio.to_thread(self._generate_sync, context)
            payload = _LLMIntentPayload.model_validate(_extract_json_object(content))
            return _payload_to_result(payload, context, fallback)
        except (ValidationError, ValueError, KeyError, json.JSONDecodeError) as exc:
            logger.warning("Invalid LLM automation intent output, using rule fallback: %s", exc)
            return fallback
        except Exception as exc:
            logger.warning("Failed to analyze automation intent with LLM, using rule fallback: %s", exc)
            return fallback

    def _generate_sync(self, context: AutomationIntentContext) -> str:
        from nexent.core.models import OpenAIModel
        from utils.config_utils import get_model_name_from_config

        language = detect_instruction_language(context.message)
        prompt_template = get_prompt_template("agent_automation", language)
        now = _analysis_time(context)
        values = {
            "message": context.message.strip(),
            "current_datetime": now.isoformat(),
            "timezone": context.timezone,
            "min_interval_seconds": AGENT_AUTOMATION_MIN_INTERVAL_SECONDS,
        }
        user_prompt = Template(
            prompt_template["INTENT_ANALYSIS_USER_PROMPT"],
            undefined=StrictUndefined,
        ).render(**values).strip()
        llm = OpenAIModel(
            model_id=get_model_name_from_config(self._model_config),
            api_base=self._model_config.get("base_url", ""),
            api_key=self._model_config.get("api_key", ""),
            temperature=0.1,
            top_p=0.9,
            max_output_tokens=700,
            model_factory=self._model_config.get("model_factory"),
            ssl_verify=self._model_config.get("ssl_verify", True),
            display_name=self._model_config.get("display_name"),
            timeout_seconds=self._model_config.get("timeout_seconds"),
            stream=False,
        )
        response = llm.generate([
            {
                "role": MESSAGE_ROLE["SYSTEM"],
                "content": prompt_template["INTENT_ANALYSIS_SYSTEM_PROMPT"],
            },
            {"role": MESSAGE_ROLE["USER"], "content": user_prompt},
        ])
        return getattr(response, "content", "") or ""


class AutomationIntentStrategyFactory:
    def create(self, context: AutomationIntentContext) -> AutomationIntentAnalysisStrategy:
        fallback = RuleBasedAutomationIntentStrategy()
        try:
            model_config = None
            if context.model_id is not None:
                selected = get_model_by_model_id(context.model_id, context.tenant_id)
                if selected and selected.get("model_type") == "llm":
                    model_config = selected
            if model_config is None:
                from utils.config_utils import tenant_config_manager

                model_config = tenant_config_manager.get_model_config(
                    key=MODEL_CONFIG_MAPPING["llm"],
                    tenant_id=context.tenant_id,
                )
            if model_config:
                return LLMAutomationIntentStrategy(model_config, fallback)
        except Exception as exc:
            logger.warning("Failed to resolve automation intent model, using rule fallback: %s", exc)
        return fallback


class AutomationIntentAnalyzer:
    def __init__(self, factory: Optional[AutomationIntentStrategyFactory] = None):
        self._factory = factory or AutomationIntentStrategyFactory()

    async def analyze(self, context: AutomationIntentContext) -> Dict[str, Any]:
        return await self._factory.create(context).analyze(context)


automation_intent_analyzer = AutomationIntentAnalyzer()
