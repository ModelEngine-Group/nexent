import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional

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
_SCHEDULE_NOISE_PATTERNS = (
    re.compile(r"(?:每天|每日|每晚|每周|每星期|每月|每年|每季度|工作日|周末)"),
    re.compile(r"每(?:隔\s*)?(?:\d+|[一二两三四五六七八九十百半]+)?\s*(?:秒|分钟|小时|天|周)"),
    re.compile(r"(?:上午|早上|中午|下午|晚上|凌晨|午夜)?\s*\d{1,2}\s*(?:[:：点时])"),
    re.compile(r"\b(?:every|daily|weekly|monthly|yearly)\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class AutomationPromptContext:
    """Data required to generate stable task content at creation time."""

    tenant_id: str
    instruction: str
    language: str = LANGUAGE["ZH"]


@dataclass(frozen=True)
class AutomationTaskContent:
    """Stable title and single-run instruction stored on an automation task."""

    title: str
    instruction: str


def detect_instruction_language(instruction: str) -> str:
    """Select the prompt language from the extracted business action."""
    return LANGUAGE["ZH"] if re.search(r"[\u3400-\u9fff]", instruction) else LANGUAGE["EN"]


def _normalize_model_output(content: str, fallback: str, max_length: int, source: str = "") -> str:
    normalized = re.sub(r"<think>[\s\S]*?</think>", "", content or "", flags=re.IGNORECASE).strip()
    normalized = normalized.removeprefix("```text").removeprefix("```markdown").strip("`\n ")
    if not normalized:
        return fallback
    normalized_lower = normalized.casefold()
    source_lower = source.casefold()
    has_orchestration_noise = any(
        term in normalized_lower and term not in source_lower
        for term in _ORCHESTRATION_TERMS
    )
    has_schedule_noise = any(
        pattern.search(normalized) and not pattern.search(source)
        for pattern in _SCHEDULE_NOISE_PATTERNS
    )
    if has_orchestration_noise or has_schedule_noise:
        logger.warning("Generated automation instruction added orchestration details; using direct fallback")
        return fallback
    if len(normalized) > max_length:
        logger.warning("Generated automation instruction exceeded the length limit; using direct fallback")
        return fallback
    return normalized


def _fallback_title(instruction: str) -> str:
    title = re.sub(r"\s+", " ", instruction).strip(" ，,。；;：:\"'“”")
    title = re.sub(r"^算一下", "计算", title)
    title = re.sub(r"^查一下", "查询", title)
    title = re.sub(r"^看一下", "查看", title)
    if title.startswith("提醒我") and len(title) > 3:
        title = f"{title[3:]}提醒"
    title = re.sub(
        r"^(发送|发|生成|整理|检查|汇总|总结|推送|发布|"
        r"备份|同步|扫描|清理|更新|导出|统计|记录)"
        r"(?:一次|一条|一句|一个|一份)",
        r"\1",
        title,
    )
    if title.startswith("发") and not title.startswith(("发送", "发布", "发现", "发起")):
        title = f"发送{title[1:]}"
    max_length = 20 if detect_instruction_language(instruction) == LANGUAGE["ZH"] else 60
    return title[:max_length] or "自动任务"


def _extract_json(content: str) -> Dict[str, Any]:
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
        raise ValueError("Automation task content must be a JSON object.")
    return parsed


def _normalize_task_content(
    content: str,
    fallback: AutomationTaskContent,
    source: str,
) -> AutomationTaskContent:
    try:
        parsed = _extract_json(content)
        if set(parsed) != {"title", "instruction"}:
            raise ValueError("Automation task content must contain only title and instruction.")
        raw_instruction = str(parsed.get("instruction") or "")
        instruction = _normalize_model_output(
            raw_instruction,
            fallback.instruction,
            300,
            source=source,
        )
        if instruction == fallback.instruction and raw_instruction.strip() != fallback.instruction:
            return fallback
        source_language = detect_instruction_language(source)
        if detect_instruction_language(instruction) != source_language:
            logger.warning("Generated automation instruction changed the source language; using direct fallback")
            return fallback
        raw_title = str(parsed.get("title") or "")
        fallback_title = _fallback_title(instruction)
        title_max_length = 20 if source_language == LANGUAGE["ZH"] else 60
        title = _normalize_model_output(
            raw_title,
            fallback_title,
            title_max_length,
            source=source,
        )
        if title == fallback_title and raw_title.strip() != fallback_title:
            return fallback
        if detect_instruction_language(title) != source_language:
            logger.warning("Generated automation title changed the source language; using direct fallback")
            return fallback
        return AutomationTaskContent(title=title, instruction=instruction)
    except Exception as exc:
        logger.warning("Failed to parse structured automation task content, using direct fallback: %s", exc)
        return fallback


class AutomationPromptStrategy(ABC):
    """Strategy interface for automation prompt generation."""

    @abstractmethod
    async def generate_task_content(self, context: AutomationPromptContext) -> AutomationTaskContent:
        raise NotImplementedError


class TemplateAutomationPromptStrategy(AutomationPromptStrategy):
    """Deterministic and fail-open prompt generation strategy."""

    async def generate_task_content(self, context: AutomationPromptContext) -> AutomationTaskContent:
        instruction = context.instruction.strip()
        return AutomationTaskContent(title=_fallback_title(instruction), instruction=instruction)


class LLMAutomationPromptStrategy(AutomationPromptStrategy):
    """LLM-backed strategy with a deterministic fallback strategy."""

    def __init__(self, model_config: Dict[str, Any], fallback: AutomationPromptStrategy):
        self._model_config = model_config
        self._fallback = fallback

    async def generate_task_content(self, context: AutomationPromptContext) -> AutomationTaskContent:
        fallback = await self._fallback.generate_task_content(context)
        try:
            content = await asyncio.to_thread(
                self._generate_sync,
                context,
                "TASK_CONTENT_SYSTEM_PROMPT",
                "TASK_CONTENT_USER_PROMPT",
            )
            return _normalize_task_content(content, fallback, context.instruction)
        except Exception as exc:
            logger.warning("Failed to generate automation task content, using direct fallback: %s", exc)
            return fallback

    def _generate_sync(
        self,
        context: AutomationPromptContext,
        system_key: str,
        user_key: str,
    ) -> str:
        from nexent.core.models import OpenAIModel
        from utils.config_utils import get_model_name_from_config

        prompt_template = get_prompt_template("agent_automation", context.language)
        values = {"instruction": context.instruction.strip()}
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
        return getattr(response, "content", "") or ""


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

    async def generate_task_content(self, context: AutomationPromptContext) -> AutomationTaskContent:
        return await self._factory.create(context.tenant_id).generate_task_content(context)


automation_prompt_generator = AutomationPromptGenerator()
