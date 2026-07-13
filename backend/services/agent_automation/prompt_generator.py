import asyncio
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from jinja2 import StrictUndefined, Template

from consts.const import LANGUAGE, MESSAGE_ROLE, MODEL_CONFIG_MAPPING
from utils.prompt_template_utils import get_prompt_template

logger = logging.getLogger("agent_automation.prompt_generator")


_ORCHESTRATION_TERMS = (
    "定时任务",
    "自动任务",
    "计划时间",
    "触发类型",
    "时区",
    "已绑定",
    "工具能力",
    "配置文件",
    "重试",
    "失败",
    "错误",
    "异常",
    "日志",
    "当前会话",
    "会话上下文",
    "不要编造",
    "scheduled task",
    "automation task",
    "scheduled time",
    "trigger type",
    "timezone",
    "bound capabilities",
    "configuration file",
    "retry",
    "if it fails",
    "on failure",
    "error handling",
    "error log",
    "current conversation",
    "conversation context",
    "do not fabricate",
    "agent",
    "tool",
    "utc",
)


@dataclass(frozen=True)
class AutomationPromptContext:
    """Data required to generate a task instruction or a single-run prompt."""

    tenant_id: str
    instruction: str
    agent_snapshot: Dict[str, Any] = field(default_factory=dict)
    capability_bindings: List[Dict[str, Any]] = field(default_factory=list)
    title: str = ""
    timezone: str = "Asia/Shanghai"
    scheduled_fire_at: Optional[datetime] = None
    trigger_type: str = "SCHEDULED"
    conversation_context: str = ""
    language: str = LANGUAGE["ZH"]


def _capability_summary(bindings: List[Dict[str, Any]], language: str) -> str:
    if not bindings:
        return (
            "当前没有绑定特定能力。"
            if language == LANGUAGE["ZH"]
            else "No specific capabilities are bound."
        )

    lines = []
    for binding in bindings:
        label = binding.get("display_name") or binding.get("name") or binding.get("binding_ref")
        lines.append(f"- {binding.get('type', 'CAPABILITY')}: {label}")
    return "\n".join(lines)


def _normalize_model_output(content: str, fallback: str, max_length: int, source: str = "") -> str:
    normalized = re.sub(r"<think>[\s\S]*?</think>", "", content or "", flags=re.IGNORECASE).strip()
    normalized = normalized.removeprefix("```text").removeprefix("```markdown").strip("`\n ")
    if not normalized:
        return fallback
    normalized_lower = normalized.casefold()
    source_lower = source.casefold()
    if any(term in normalized_lower and term not in source_lower for term in _ORCHESTRATION_TERMS):
        logger.warning("Generated automation instruction added orchestration details; using direct fallback")
        return fallback
    if len(normalized) > max_length:
        logger.warning("Generated automation instruction exceeded the length limit; using direct fallback")
        return fallback
    return normalized


class AutomationPromptStrategy(ABC):
    """Strategy interface for automation prompt generation."""

    @abstractmethod
    async def optimize_instruction(self, context: AutomationPromptContext) -> str:
        raise NotImplementedError

    @abstractmethod
    async def generate_execution_prompt(self, context: AutomationPromptContext) -> str:
        raise NotImplementedError


class TemplateAutomationPromptStrategy(AutomationPromptStrategy):
    """Deterministic and fail-open prompt generation strategy."""

    def _render(self, context: AutomationPromptContext, template_key: str) -> str:
        prompt_template = get_prompt_template("agent_automation", context.language)
        agent_name = context.agent_snapshot.get("name") or f"Agent #{context.agent_snapshot.get('agent_id', '')}"
        values = {
            "title": context.title or context.instruction[:30],
            "instruction": context.instruction.strip(),
            "agent_name": agent_name,
            "agent_description": context.agent_snapshot.get("description", ""),
            "capability_summary": _capability_summary(context.capability_bindings, context.language),
            "scheduled_fire_at": context.scheduled_fire_at.isoformat() if context.scheduled_fire_at else "",
            "timezone": context.timezone,
            "trigger_type": context.trigger_type,
            "conversation_context": context.conversation_context,
        }
        return Template(prompt_template[template_key], undefined=StrictUndefined).render(**values).strip()

    async def optimize_instruction(self, context: AutomationPromptContext) -> str:
        return self._render(context, "FALLBACK_INSTRUCTION_PROMPT")

    async def generate_execution_prompt(self, context: AutomationPromptContext) -> str:
        return self._render(context, "FALLBACK_EXECUTION_PROMPT")


class LLMAutomationPromptStrategy(AutomationPromptStrategy):
    """LLM-backed strategy with a deterministic fallback strategy."""

    def __init__(self, model_config: Dict[str, Any], fallback: AutomationPromptStrategy):
        self._model_config = model_config
        self._fallback = fallback

    async def optimize_instruction(self, context: AutomationPromptContext) -> str:
        fallback = await self._fallback.optimize_instruction(context)
        return await self._generate(
            context,
            system_key="INSTRUCTION_SYSTEM_PROMPT",
            user_key="INSTRUCTION_USER_PROMPT",
            fallback=fallback,
            max_length=300,
        )

    async def generate_execution_prompt(self, context: AutomationPromptContext) -> str:
        # The task instruction is already generated and confirmed when the task is created.
        # Reusing it keeps scheduled runs stable and prevents runtime metadata from leaking
        # into the user-facing prompt.
        return await self._fallback.generate_execution_prompt(context)

    async def _generate(
        self,
        context: AutomationPromptContext,
        system_key: str,
        user_key: str,
        fallback: str,
        max_length: int,
    ) -> str:
        try:
            return await asyncio.to_thread(
                self._generate_sync,
                context,
                system_key,
                user_key,
                fallback,
                max_length,
            )
        except Exception as exc:
            logger.warning("Failed to optimize agent automation prompt, using template fallback: %s", exc)
            return fallback

    def _generate_sync(
        self,
        context: AutomationPromptContext,
        system_key: str,
        user_key: str,
        fallback: str,
        max_length: int,
    ) -> str:
        from nexent.core.models import OpenAIModel
        from utils.config_utils import get_model_name_from_config

        prompt_template = get_prompt_template("agent_automation", context.language)
        agent_name = context.agent_snapshot.get("name") or f"Agent #{context.agent_snapshot.get('agent_id', '')}"
        values = {
            "title": context.title or context.instruction[:30],
            "instruction": context.instruction.strip(),
            "agent_name": agent_name,
            "agent_description": context.agent_snapshot.get("description", ""),
            "capability_summary": _capability_summary(context.capability_bindings, context.language),
            "scheduled_fire_at": context.scheduled_fire_at.isoformat() if context.scheduled_fire_at else "",
            "timezone": context.timezone,
            "trigger_type": context.trigger_type,
            "conversation_context": context.conversation_context,
        }
        user_prompt = Template(prompt_template[user_key], undefined=StrictUndefined).render(**values).strip()
        llm = OpenAIModel(
            model_id=get_model_name_from_config(self._model_config) if self._model_config.get("model_name") else "",
            api_base=self._model_config.get("base_url", ""),
            api_key=self._model_config.get("api_key", ""),
            temperature=0.2,
            top_p=0.9,
            model_factory=self._model_config.get("model_factory"),
            ssl_verify=self._model_config.get("ssl_verify", True),
            timeout_seconds=self._model_config.get("timeout_seconds"),
            stream=False,
        )
        response = llm.generate([
            {"role": MESSAGE_ROLE["SYSTEM"], "content": prompt_template[system_key]},
            {"role": MESSAGE_ROLE["USER"], "content": user_prompt},
        ])
        return _normalize_model_output(
            getattr(response, "content", "") or "",
            fallback,
            max_length,
            source=context.instruction,
        )


class AutomationPromptStrategyFactory:
    """Factory that selects an LLM strategy when the tenant has a usable model."""

    def create(self, tenant_id: str) -> AutomationPromptStrategy:
        fallback = TemplateAutomationPromptStrategy()
        try:
            from utils.config_utils import tenant_config_manager

            model_config = tenant_config_manager.get_model_config(
                key=MODEL_CONFIG_MAPPING["llm"],
                tenant_id=tenant_id,
            )
            if model_config:
                return LLMAutomationPromptStrategy(model_config, fallback)
        except Exception as exc:
            logger.warning("Failed to resolve automation prompt model, using template strategy: %s", exc)
        return fallback


class AutomationPromptGenerator:
    """Application service that keeps prompt strategy selection out of callers."""

    def __init__(self, factory: Optional[AutomationPromptStrategyFactory] = None):
        self._factory = factory or AutomationPromptStrategyFactory()

    async def optimize_instruction(self, context: AutomationPromptContext) -> str:
        return await self._factory.create(context.tenant_id).optimize_instruction(context)

    async def generate_execution_prompt(self, context: AutomationPromptContext) -> str:
        return await self._factory.create(context.tenant_id).generate_execution_prompt(context)


automation_prompt_generator = AutomationPromptGenerator()
