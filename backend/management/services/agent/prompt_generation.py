# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import copy
import json
import logging
from typing import Optional, List

from nexent.core.agents.prompt.auxiliary import compose_auxiliary_prompt
from nexent.core.agents.prompt.meta import (
    append_optimization_scope_instruction, compose_agent_optimization,
    default_section_title, optimization_scope_instruction,
)

from nexent.core.tools.parallel_executor import ParallelExecutorTool

from contracts.constants.constants import LANGUAGE
from contracts.constants.environment import ENABLE_JIUWEN_SDK
from contracts.constants.constants import PARALLEL_EXECUTOR_TOOL_NAME
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from management.db.agent.repository import search_agent_info_by_agent_id, query_sub_agents_id_list
from management.db.tool.repository import query_tools_by_ids
from management.services.agent.service import get_enable_tool_id_by_agent_id
from management.services.model.invocation import call_llm_for_system_prompt

from typing import Optional as Opt

from adapters.exception import JiuwenSDKError, NexentCapabilityError


def _get_jiuwen_adapter_class():
    """Import Jiuwen adapter only when optimization paths need it."""
    try:
        from adapters import JiuwenSDKAdapter
    except ModuleNotFoundError:
        return None
    return JiuwenSDKAdapter


# Configure logging
logger = logging.getLogger("prompt_service")

def _resolve_knowledge_tool_capabilities(
    tool_info_list: List[dict],
) -> tuple[bool, bool]:
    """Return knowledge capabilities without exposing configured resource names."""
    identifiers = {
        str(tool.get(key) or "").strip().lower()
        for tool in tool_info_list
        for key in ("name", "class_name")
    }
    has_local = bool(
        identifiers
        & {
            "knowledgebasesearchtool",
            "knowledge_base_search",
        }
    )
    has_aidp = bool(
        identifiers
        & {
            "aidpsearchtool",
            "aidp_search",
        }
    )
    return has_local, has_aidp


def _knowledge_agnostic_optimization_instruction(language: str) -> str:
    """Build the invariant appended to every prompt optimization entry point."""
    return optimization_scope_instruction(language)


def _append_knowledge_agnostic_instruction(feedback: str, language: str) -> str:
    return append_optimization_scope_instruction(feedback, language)


def _copy_bad_cases_with_scope_instruction(bad_cases: list, language: str) -> list:
    """Copy Jiuwen bad cases and harden their feedback without mutating callers."""
    copied_cases = []
    for bad_case in bad_cases:
        if isinstance(bad_case, dict):
            copied_case = dict(bad_case)
            copied_case["reason"] = _append_knowledge_agnostic_instruction(
                str(copied_case.get("reason") or ""), language
            )
        else:
            copied_case = copy.copy(bad_case)
            copied_case.reason = _append_knowledge_agnostic_instruction(
                str(getattr(copied_case, "reason", "") or ""), language
            )
        copied_cases.append(copied_case)
    return copied_cases


def optimize_prompt_section_impl(
    agent_id: int,
    model_id: int,
    task_description: str,
    tenant_id: str,
    language: str,
    section_type: str,
    section_title: str,
    current_content: str,
    feedback: str,
    tool_ids: Optional[List[int]] = None,
    sub_agent_ids: Optional[List[int]] = None,
    knowledge_base_display_names: Optional[List[str]] = None,
    aidp_kb_display_names: Optional[List[str]] = None,
) -> dict:
    normalized_section_type = (section_type or "").strip()
    if normalized_section_type not in {"duty", "constraint", "few_shots"}:
        raise AppException(
            ErrorCode.COMMON_PARAMETER_INVALID,
            "Unsupported prompt section type."
        )

    if not (current_content or "").strip():
        raise AppException(
            ErrorCode.COMMON_MISSING_REQUIRED_FIELD,
            "Current section content is required."
        )

    if not (feedback or "").strip():
        raise AppException(
            ErrorCode.COMMON_MISSING_REQUIRED_FIELD,
            "Optimization feedback is required."
        )

    tool_info_list = _resolve_prompt_tools(
        agent_id=agent_id,
        tenant_id=tenant_id,
        tool_ids=tool_ids,
    )
    knowledge_base_display_names = None
    aidp_kb_display_names = None
    sub_agent_info_list = _resolve_prompt_sub_agents(
        agent_id=agent_id,
        tenant_id=tenant_id,
        sub_agent_ids=sub_agent_ids,
    )

    has_local_knowledge_tool, has_aidp_knowledge_tool = _resolve_knowledge_tool_capabilities(tool_info_list)
    resolved_title = section_title or _default_prompt_section_title(normalized_section_type, language)
    prompt = compose_agent_optimization(
        language,
        section_type=normalized_section_type,
        section_title=resolved_title,
        task_description=task_description,
        current_content=current_content,
        feedback=feedback,
        tools=tool_info_list,
        worker_agents=sub_agent_info_list,
        has_local_knowledge_tool=has_local_knowledge_tool,
        has_aidp_knowledge_tool=has_aidp_knowledge_tool,
    )

    optimized_content = call_llm_for_system_prompt(
        model_id=model_id,
        user_prompt=prompt.user,
        system_prompt=prompt.system,
        tenant_id=tenant_id,
    ).strip()

    if not optimized_content:
        raise AppException(ErrorCode.MODEL_PROMPT_GENERATION_FAILED)

    return {
        "section_type": normalized_section_type,
        "section_title": resolved_title,
        "original_content": current_content,
        "optimized_content": optimized_content,
    }


def _extract_json_object(raw: str) -> Optional[dict]:
    """Extract the first JSON object from LLM output that may contain markdown fences / surrounding text.

    Fallbacks: markdown fence, surrounding explanation text, single quotes, trailing commas.
    """
    text = (raw or "").strip()
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    snippet = text[start:end + 1]
    try:
        return json.loads(snippet)
    except (ValueError, TypeError):
        pass
    # Fallback: single quotes -> double quotes, strip trailing commas
    import re as _re
    try:
        fixed = snippet.replace("'", '"')
        fixed = _re.sub(r",\s*([}\]])", r"\1", fixed)
        return json.loads(fixed)
    except (ValueError, TypeError):
        pass
    # Fallback: LLM often inlines regex escapes (\d \w \s \. etc.) directly into JSON strings.
    # A single backslash is invalid in JSON (only \" \\ \/ \b \f \n \r \t \uXXXX are allowed).
    # Double up backslashes that are not part of a valid JSON escape sequence.
    try:
        fixed = _re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', snippet)
        return json.loads(fixed)
    except (ValueError, TypeError):
        return None


def generate_guardrail_rules_impl(
    description: str,
    model_id: int,
    tenant_id: str,
    language: str = LANGUAGE["ZH"],
) -> dict:
    """Generate guardrail regex rules from a natural-language description via LLM.

    Loads the guardrail prompt template, renders the user prompt with the
    description, calls the LLM, and extracts the JSON object from the (possibly
    malformed) response. Tolerates markdown fences, surrounding prose, single
    quotes, trailing commas, and invalid JSON escapes such as ``\\d`` (LLMs
    often paste regex escapes with a single backslash).

    Args:
        description: Natural-language description of what to match or block.
        model_id: ID of the LLM model used for generation.
        tenant_id: Tenant ID for model resolution and monitoring.
        language: Language code ('zh' or 'en') selecting the prompt template.

    Returns:
        A dict keyed by ``type``:
        - ``{"type": "single", "candidates": [{"pattern": str, "desc": str}]}``
        - ``{"type": "multi", "rules": [{"name": str, "pattern": str,
          "severity": str, "desc": str}]}``

    Raises:
        AppException: If ``description`` is empty, the LLM returns nothing,
            or the response is not valid JSON / carries an unknown ``type``.
    """

    if not (description or "").strip():
        raise AppException(
            ErrorCode.COMMON_MISSING_REQUIRED_FIELD,
            "Description is required.",
        )

    prompt = compose_auxiliary_prompt(language, "guardrail_regex", {"description": description})

    raw = call_llm_for_system_prompt(
        model_id=model_id,
        user_prompt=prompt.user,
        system_prompt=prompt.system,
        tenant_id=tenant_id,
    ).strip()

    # Diagnostic log: record raw LLM output (for troubleshooting "bad format" issues)
    logger.info("[guardrail] desc=%r model_id=%s raw(500)=%s", description[:80], model_id, (raw or "")[:500])

    if not raw:
        raise AppException(ErrorCode.MODEL_PROMPT_GENERATION_FAILED)

    parsed = _extract_json_object(raw)
    if not isinstance(parsed, dict):
        logger.warning("[guardrail] JSON parse failed, raw=%s", (raw or "")[:800])
        raise AppException(
            ErrorCode.MODEL_PROMPT_GENERATION_FAILED,
            "LLM did not return valid JSON for guardrail rules.",
        )

    result_type = str(parsed.get("type") or "").strip().lower()
    if result_type == "single":
        candidates = parsed.get("candidates")
        return {"type": "single", "candidates": candidates if isinstance(candidates, list) else []}
    if result_type == "multi":
        rules = parsed.get("rules")
        return {"type": "multi", "rules": rules if isinstance(rules, list) else []}
    raise AppException(
        ErrorCode.MODEL_PROMPT_GENERATION_FAILED,
        "Unknown guardrail result type.",
    )


def _resolve_prompt_tools(
    agent_id: int,
    tenant_id: str,
    tool_ids: Optional[List[int]] = None,
) -> List[dict]:
    if tool_ids and len(tool_ids) > 0:
        logger.debug(f"Using frontend-provided tool IDs: {tool_ids}")
        return query_tools_by_ids(tool_ids)

    logger.debug("No tools selected (empty tool_ids list)")
    return _get_enabled_tool_descriptions(
        tenant_id=tenant_id, agent_id=agent_id
    )


def _resolve_prompt_sub_agents(
    agent_id: int,
    tenant_id: str,
    sub_agent_ids: Optional[List[int]] = None,
) -> List[dict]:
    if sub_agent_ids and len(sub_agent_ids) > 0:
        sub_agent_info_list = []
        for sub_agent_id in sub_agent_ids:
            try:
                sub_agent_info = search_agent_info_by_agent_id(
                    agent_id=sub_agent_id, tenant_id=tenant_id)
                sub_agent_info_list.append(sub_agent_info)
            except Exception as exc:
                logger.warning(
                    f"Failed to get sub-agent info for agent_id {sub_agent_id}: {str(exc)}"
                )
        logger.debug(f"Using frontend-provided sub-agent IDs: {sub_agent_ids}")
        return sub_agent_info_list

    logger.debug("No sub-agents selected (empty sub_agent_ids list)")
    return _get_enabled_sub_agent_descriptions(
        tenant_id=tenant_id, agent_id=agent_id
    )


def join_info_for_optimize_prompt_section(
    prompt_for_optimize,
    section_type: str,
    section_title: str,
    task_description: str,
    current_content: str,
    feedback: str,
    tool_info_list,
    sub_agent_info_list,
    language: str = LANGUAGE["ZH"],
    knowledge_base_display_names: Optional[List[str]] = None,
    aidp_kb_display_names: Optional[List[str]] = None,
):
    has_local_knowledge_tool, has_aidp_knowledge_tool = _resolve_knowledge_tool_capabilities(
        tool_info_list
    )
    return compose_agent_optimization(
        language,
        section_type=section_type,
        section_title=section_title,
        task_description=task_description,
        current_content=current_content,
        feedback=feedback,
        tools=tool_info_list,
        worker_agents=sub_agent_info_list,
        has_local_knowledge_tool=has_local_knowledge_tool,
        has_aidp_knowledge_tool=has_aidp_knowledge_tool,
        template_override=prompt_for_optimize,
    ).user


def _default_prompt_section_title(section_type: str, language: str) -> str:
    return default_section_title(language, section_type)


def _get_enabled_tool_descriptions(agent_id: int, tenant_id: str):
    # Get tool information
    logger.info("Fetching tool instances")
    tool_id_list = get_enable_tool_id_by_agent_id(
        agent_id=agent_id, tenant_id=tenant_id)
    # If no tools are enabled, return early — nothing to parallelize.
    if not tool_id_list:
        return []
    tool_info_list = query_tools_by_ids(tool_id_list)

    # parallel_executor is always built from the SDK class — no DB query.
    seen_names = {t.get("name") for t in tool_info_list if t.get("name")}
    if PARALLEL_EXECUTOR_TOOL_NAME not in seen_names:
        tool_info_list.append({
            "name": ParallelExecutorTool.name,
            "description": ParallelExecutorTool.description,
            "description_zh": ParallelExecutorTool.description_zh,
            "inputs": json.dumps(ParallelExecutorTool.inputs, ensure_ascii=False),
            "output_type": ParallelExecutorTool.output_type,
            "params": [],
            "source": "local",
            "class_name": ParallelExecutorTool.__name__,
        })

    return tool_info_list


def _get_enabled_sub_agent_descriptions(agent_id: int, tenant_id: str):
    logger.info("Fetching sub-agents information")

    sub_agent_id_list = query_sub_agents_id_list(
        main_agent_id=agent_id, tenant_id=tenant_id)

    sub_agent_info_list = []
    for sub_agent_id in sub_agent_id_list:
        sub_agent_info = search_agent_info_by_agent_id(
            agent_id=sub_agent_id, tenant_id=tenant_id)

        sub_agent_info_list.append(sub_agent_info)
    return sub_agent_info_list


# ── Jiuwen SDK 集成 ───────────────────────────────────────────────────────────


from contracts.agent import OptimizeRequest


from contracts.agent import OptimizeResult


class PromptOptimizationService:
    """提示词优化服务 — 统一入口，模式二选一"""

    def optimize_from_debug(self, agent_id: int, feedback: str, selected, history=None) -> OptimizeResult:
        """基于调试对话自动优化整个 system prompt（完整模板）。

        Args:
            selected: OptimizeFromDebugSelected (pydantic model) or any object with user_question/assistant_answer.
            history: Optional[List[HistoryItem]]
        """
        if not (feedback or "").strip():
            raise AppException(
                ErrorCode.COMMON_MISSING_REQUIRED_FIELD,
                "Optimization feedback is required.",
            )

        if not self.is_jiuwen_mode_available():
            raise NexentCapabilityError(
                "Auto optimize from debug requires Jiuwen SDK to be enabled."
            )

        agent_info = search_agent_info_by_agent_id(
            agent_id=agent_id, tenant_id=self.tenant_id, version_no=0)

        original_full_prompt = (agent_info.get("prompt") or "").strip()

        if not original_full_prompt:
            raise AppException(
                ErrorCode.COMMON_MISSING_REQUIRED_FIELD,
                "Agent system prompt is empty.",
            )

        user_question = getattr(selected, "user_question", None) or (
            selected.get("user_question") if isinstance(selected, dict) else "")
        assistant_answer = getattr(selected, "assistant_answer", None) or (
            selected.get("assistant_answer") if isinstance(selected, dict) else "")

        bad_case_obj = type("_BadCase", (), {})
        bc = bad_case_obj()
        bc.question = user_question or ""
        bc.answer = assistant_answer or ""
        bc.label = ""
        bc.reason = _append_knowledge_agnostic_instruction(feedback, self.language)

        adapter_cls = _get_jiuwen_adapter_class()
        if adapter_cls is None:
            raise JiuwenSDKError("Jiuwen SDK adapter is unavailable")

        adapter = adapter_cls(
            model_id=self.model_id, tenant_id=self.tenant_id)

        optimized_full_prompt = adapter.optimize_badcase(
            prompt=original_full_prompt,
            bad_cases=[bc],
            language=self.language,
        )

        return OptimizeResult(
            optimized_content=optimized_full_prompt,
            source="jiuwen",
            section_type="full_prompt",
            section_title="system_prompt",
            original_content=original_full_prompt,
        )

    def __init__(self, model_id: int, tenant_id: str, language: str):
        self.model_id = model_id
        self.tenant_id = tenant_id
        self.language = language

    def is_jiuwen_mode_available(self) -> bool:
        """判断 Jiuwen SDK 模式是否可用"""
        if not ENABLE_JIUWEN_SDK:
            return False

        return _get_jiuwen_adapter_class() is not None

    def optimize(self, request: OptimizeRequest) -> OptimizeResult:
        """统一优化入口 — 优先 Jiuwen SDK，失败则降级 nexent 原生"""
        if self.is_jiuwen_mode_available():
            logger.info(
                f"[prompt-optimize] mode={request.mode}, using Jiuwen SDK")
            try:
                return self._optimize_with_jiuwen(request)
            except JiuwenSDKError as e:
                logger.warning(f"Jiuwen SDK 模式失败，降级到 nexent 原生: {e}")
                return self._optimize_with_nexent(request)
        else:
            return self._optimize_with_nexent(request)

    def _optimize_with_jiuwen(self, request: OptimizeRequest) -> OptimizeResult:
        """Jiuwen SDK 模式"""
        logger.info(
            f"[jiuwen-optimize] mode={request.mode}, start_pos={request.start_pos}, "
            f"end_pos={request.end_pos}, prompt_len={len(request.current_content)}, "
            f"feedback_len={len(request.feedback)}"
        )
        adapter_cls = _get_jiuwen_adapter_class()
        if adapter_cls is None:
            raise JiuwenSDKError("Jiuwen SDK adapter is unavailable")

        adapter = adapter_cls(
            model_id=self.model_id,
            tenant_id=self.tenant_id,
        )
        result = adapter.optimize(
            prompt=request.current_content,
            feedback=_append_knowledge_agnostic_instruction(
                request.feedback, self.language
            ),
            mode=request.mode,
            start_pos=request.start_pos,
            end_pos=request.end_pos,
            language=self.language,
        )

        # Jiuwen insert/select mode returns a fragment by design.
        # We reassemble the full prompt here so frontend always receives full optimized content.
        if request.mode == "insert":
            if request.start_pos is None or not isinstance(request.start_pos, int):
                raise JiuwenSDKError("insert mode requires start_pos")
            if request.start_pos < 0 or request.start_pos > len(request.current_content):
                raise JiuwenSDKError("insert mode start_pos out of bounds")
            optimized_full = (
                request.current_content[: request.start_pos]
                + result
                + request.current_content[request.start_pos:]
            )
        elif request.mode == "select":
            if request.start_pos is None or request.end_pos is None:
                raise JiuwenSDKError(
                    "select mode requires start_pos and end_pos")
            if not isinstance(request.start_pos, int) or not isinstance(request.end_pos, int):
                raise JiuwenSDKError(
                    "select mode start_pos/end_pos must be int")
            if request.start_pos < 0 or request.end_pos < 0 or request.start_pos >= request.end_pos:
                raise JiuwenSDKError("select mode start_pos/end_pos invalid")
            if request.end_pos > len(request.current_content):
                raise JiuwenSDKError("select mode end_pos out of bounds")
            optimized_full = (
                request.current_content[: request.start_pos]
                + result
                + request.current_content[request.end_pos:]
            )
        else:
            optimized_full = result

        return OptimizeResult(
            optimized_content=optimized_full,
            source="jiuwen",
            section_type=request.section_type,
            section_title=request.section_title,
            original_content=request.current_content,
        )

    def _optimize_with_nexent(self, request: OptimizeRequest) -> OptimizeResult:
        """nexent 原生模式 — 只支持 general 模式"""
        if request.mode != "general":
            raise NexentCapabilityError(
                f"nexent 原生模式只支持 general 模式，"
                f"当前请求 mode={request.mode} 不支持，请启用 Jiuwen SDK"
            )

        result = optimize_prompt_section_impl(
            agent_id=request.agent_id,
            model_id=self.model_id,
            task_description=request.task_description,
            tenant_id=self.tenant_id,
            language=self.language,
            section_type=request.section_type,
            section_title=request.section_title,
            current_content=request.current_content,
            feedback=request.feedback,
            tool_ids=request.tool_ids,
            sub_agent_ids=request.sub_agent_ids,
            knowledge_base_display_names=request.knowledge_base_display_names,
        )
        return OptimizeResult(
            optimized_content=result["optimized_content"],
            source="nexent",
            section_type=result["section_type"],
            section_title=result["section_title"],
            original_content=result["original_content"],
        )

    def optimize_badcase(
        self,
        current_content: str,
        bad_cases: list,
        agent_id: int,
        section_type: str,
        section_title: str,
        tool_ids: Opt[list[int]] = None,
        sub_agent_ids: Opt[list[int]] = None,
        knowledge_base_display_names: Opt[list[str]] = None,
    ) -> OptimizeResult:
        """坏案例优化入口 — 优先 Jiuwen SDK，失败则降级"""
        if self.is_jiuwen_mode_available():
            logger.info("[prompt-badcase] using Jiuwen SDK")
            try:
                return self._optimize_badcase_with_jiuwen(
                    current_content, bad_cases, section_type, section_title
                )
            except JiuwenSDKError as e:
                logger.warning(f"Jiuwen SDK badcase 模式失败，降级到 nexent 原生: {e}")
                return self._optimize_badcase_with_nexent(
                    current_content, bad_cases, agent_id, section_type, section_title,
                    tool_ids, sub_agent_ids, knowledge_base_display_names,
                )
        else:
            return self._optimize_badcase_with_nexent(
                current_content, bad_cases, agent_id, section_type, section_title,
                tool_ids, sub_agent_ids, knowledge_base_display_names,
            )

    def _optimize_badcase_with_jiuwen(
        self, current_content: str, bad_cases: list, section_type: str, section_title: str
    ) -> OptimizeResult:
        """Jiuwen SDK 坏案例优化"""
        adapter_cls = _get_jiuwen_adapter_class()
        if adapter_cls is None:
            raise JiuwenSDKError("Jiuwen SDK adapter is unavailable")

        adapter = adapter_cls(
            model_id=self.model_id,
            tenant_id=self.tenant_id,
        )
        result = adapter.optimize_badcase(
            prompt=current_content,
            bad_cases=_copy_bad_cases_with_scope_instruction(
                bad_cases, self.language
            ),
            language=self.language,
        )
        return OptimizeResult(
            optimized_content=result,
            source="jiuwen",
            section_type=section_type,
            section_title=section_title,
            original_content=current_content,
        )

    def _optimize_badcase_with_nexent(
        self,
        current_content: str,
        bad_cases: list,
        agent_id: int,
        section_type: str,
        section_title: str,
        tool_ids: Opt[list[int]] = None,
        sub_agent_ids: Opt[list[int]] = None,
        knowledge_base_display_names: Opt[list[str]] = None,
    ) -> OptimizeResult:
        """nexent 原生模式不支持坏案例优化"""
        raise NexentCapabilityError(
            "nexent 原生模式不支持 badcase 优化，请启用 Jiuwen SDK"
        )
