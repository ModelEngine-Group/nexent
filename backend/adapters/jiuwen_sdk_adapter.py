"""OpenJiuwen prompt optimization adapter for Nexent."""

import asyncio
import json
import logging
from typing import Any, List, Literal, Optional, Tuple

from adapters.openjiuwen_compat import (
    NEXENT_OPENAI_CLIENT_PROVIDER,
    OpenJiuwenCompatibilityError,
    load_openjiuwen_public_api,
    validate_openjiuwen_version,
)
from adapters.exception import JiuwenSDKError


def _install_jiuwen_bypasser() -> bool:
    """Compatibility no-op retained for callers from the 0.1.13 adapter."""
    return False


def _case_types() -> tuple[Any, Any]:
    from openjiuwen.dev_tools.tune.base import Case, EvaluatedCase

    return Case, EvaluatedCase


def _case_from_inputs_label(inputs: dict, label: dict) -> Any:
    # Keep stable keys for schema; allow extra fields to exist.
    case_type, _ = _case_types()
    return case_type(inputs=inputs, label=label)


def _extract_score_reason(evaluated: Any) -> Tuple[float, str]:
    """Try to normalize Jiuwen EvaluatedCase into (score, reason)."""
    try:
        score = float(getattr(evaluated, "score", 0.0) or 0.0)
    except Exception:
        score = 0.0
    reason = getattr(evaluated, "reason", "") or ""
    return score, str(reason)


logger = logging.getLogger("jiuwen_adapter")


# ----------------------------------------------------------------------
# Language helpers
# ----------------------------------------------------------------------
LANGUAGE_MAP = {"zh": "zh-CN", "en": "en-US"}


def normalize_language(language: str) -> str:
    return LANGUAGE_MAP.get(language, "zh-CN")


def run_async(coro):
    """
    Safely run async coroutine from sync context (FastAPI or Celery).
    Handles existing event loops properly.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    if loop.is_running():
        try:
            import nest_asyncio

            nest_asyncio.apply()
            return loop.run_until_complete(coro)
        except ImportError:
            import concurrent.futures

            def run_in_thread():
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(coro)
                finally:
                    new_loop.close()

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(run_in_thread)
                return future.result()

    return loop.run_until_complete(coro)


# ----------------------------------------------------------------------
# Jiuwen SDK lazy import helpers
# ----------------------------------------------------------------------
def _lazy_import_jiuwen():
    """延迟导入 Jiuwen SDK，避免 openjiuwen 未装时模块级 ImportError"""
    try:
        validate_openjiuwen_version()
        import openjiuwen  # noqa: F401
    except (ImportError, OpenJiuwenCompatibilityError) as e:
        raise JiuwenSDKError(f"Jiuwen SDK 未安装: {e}") from e

    from openjiuwen.core.foundation.llm.schema.config import (
        ModelRequestConfig,
        ModelClientConfig,
        ProviderType,
    )
    from openjiuwen.dev_tools.prompt_builder.builder.feedback_prompt_builder import (
        FeedbackPromptBuilder,
    )
    from openjiuwen.dev_tools.prompt_builder.builder.badcase_prompt_builder import (
        BadCasePromptBuilder,
    )
    from openjiuwen.dev_tools.tune.base import Case, EvaluatedCase

    # Evaluator metrics (avoid importing openjiuwen.dev_tools.tune package root)
    from openjiuwen.agent_evolving.evaluator.metrics.llm_as_judge import (
        LLMAsJudgeMetric,
    )

    return (
        ModelRequestConfig,
        ModelClientConfig,
        ProviderType,
        FeedbackPromptBuilder,
        BadCasePromptBuilder,
        Case,
        EvaluatedCase,
        LLMAsJudgeMetric,
    )


def build_jiuwen_model_configs(model_id: int, tenant_id: str):
    """将 nexent 模型配置转换为 Jiuwen 配置对象"""
    from database.model_management_db import get_model_by_model_id
    from utils.config_utils import get_model_name_from_config

    ModelRequestConfig, ModelClientConfig, ProviderType, _, _, _, _, _ = (
        _lazy_import_jiuwen()
    )

    model_config = get_model_by_model_id(model_id, tenant_id)
    if not model_config:
        raise JiuwenSDKError(f"model_id={model_id} not found")

    api_base = (model_config.get("base_url", "") or "").strip()
    if not api_base:
        api_base = "https://api.openai.com/v1"

    # Jiuwen ModelClientConfig defaults to timeout=60.0, max_retries=3.
    # For prompt optimization calls, 60s can be too small. Reuse Nexent model config timeout_seconds.
    timeout_seconds = model_config.get("timeout_seconds")
    if timeout_seconds is None:
        timeout_seconds = 120

    ssl_cert = model_config.get("ssl_cert") or None
    ssl_verify = model_config.get("ssl_verify", True)

    client_config = ModelClientConfig(
        client_provider=NEXENT_OPENAI_CLIENT_PROVIDER,
        api_key=model_config["api_key"],
        api_base=api_base,
        timeout=float(timeout_seconds),
        verify_ssl=ssl_verify,
        ssl_cert=ssl_cert,
    )

    request_config = ModelRequestConfig(
        model_name=get_model_name_from_config(model_config),
        temperature=0.3,
    )
    return request_config, client_config


def _build_openai_client(client_config: Any, request_config: Any) -> Any:
    """
    直接创建 OpenAIModelClient，绕过 FeedbackPromptBuilder 的深导入链。
    """
    try:
        OpenAIModelClient = load_openjiuwen_public_api().NexentOpenAIModelClient
    except OpenJiuwenCompatibilityError:
        from openjiuwen.core.foundation.llm.model_clients.openai_model_client import (
            OpenAIModelClient,
        )

    class _DirectClient:
        """对 OpenAIModelClient 的薄封装，只暴露 invoke() 方法"""

        def __init__(self, inner: Any):
            self._inner = inner
            self._model = request_config.model_name

        async def invoke(self, messages: list[dict]) -> Any:
            return await self._inner.invoke(
                model=self._model,
                messages=messages,
                temperature=request_config.temperature,
                top_p=request_config.top_p,
            )

    client = OpenAIModelClient(
        model_config=request_config, model_client_config=client_config
    )
    return _DirectClient(client)


def _build_message(role: str, content: str) -> dict:
    return {"role": role, "content": content}


def _lazy_import_jiuwen_builders():
    """Lazily import prompt builders only when optimization paths need them."""
    try:
        validate_openjiuwen_version()
        import openjiuwen  # noqa: F401
    except (ImportError, OpenJiuwenCompatibilityError) as e:
        raise JiuwenSDKError(f"Jiuwen SDK 未安装: {e}") from e

    from openjiuwen.dev_tools.prompt_builder.builder.feedback_prompt_builder import (
        FeedbackPromptBuilder,
    )
    from openjiuwen.dev_tools.prompt_builder.builder.badcase_prompt_builder import (
        BadCasePromptBuilder,
    )

    return FeedbackPromptBuilder, BadCasePromptBuilder


def _unwrap_prompt_response(text: str) -> str:
    """Strip JSON wrapper or markdown fence that Jiuwen LLM sometimes generates."""
    _logger = logging.getLogger("jiuwen_adapter")
    _logger.debug(f"[unwrap] raw ({len(text)} chars): {text[:200]}")

    # Step 1: strip markdown code fences
    text = text.strip()
    if text.startswith("```"):
        for lang in ("json", ""):
            fence = f"```{lang}\n"
            if text.startswith(fence):
                text = text[len(fence) :]
                if text.endswith("\n```"):
                    text = text[:-4]
                elif text.endswith("```"):
                    text = text[:-3]
                break
        text = text.strip()
        _logger.debug(f"[unwrap] after fence strip ({len(text)} chars)")

    # Step 2: try standard JSON parse (handles format 1 and 2)
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "prompt" in parsed:
                result = parsed["prompt"].strip()
                _logger.debug(f"[unwrap] extracted prompt ({len(result)} chars)")
                return result
            if isinstance(parsed, dict) and "result" in parsed:
                result = parsed["result"].strip()
                _logger.debug(f"[unwrap] extracted result ({len(result)} chars)")
                return result
        except Exception:
            pass

    # Step 3: format 3 and 4 - raw text (possibly multi-line), return as-is
    _logger.debug(f"[unwrap] no JSON wrapper, returning raw ({len(text)} chars)")
    return text


def to_jiuwen_evaluated_case(bad_case) -> Any:
    """将 nexent BadCase 转换为 Jiuwen EvaluatedCase"""
    _, _, _, _, _, Case, EvaluatedCase, _ = _lazy_import_jiuwen()

    case = Case(
        inputs={"question": bad_case.question},
        label={"answer": bad_case.label or ""},
    )
    return EvaluatedCase(
        case=case,
        answer={"content": bad_case.answer},
        score=0.0,
        reason=bad_case.reason or "",
    )


# ----------------------------------------------------------------------
# Main adapter class
# ----------------------------------------------------------------------
class JiuwenSDKAdapter:
    """
    Jiuwen SDK 调用适配器

    封装 Jiuwen SDK 的所有调用，内部不处理降级，
    失败时抛出 JiuwenSDKError，由上层 PromptOptimizationService 决定是否降级
    """

    def __init__(self, model_id: int, tenant_id: str):
        self.model_id = model_id
        self.tenant_id = tenant_id
        self.logger = logging.getLogger("jiuwen_adapter")

    def _ensure_available(self):
        """确保 Jiuwen SDK 可用"""
        try:
            validate_openjiuwen_version()
            import openjiuwen  # noqa: F401
        except (ImportError, OpenJiuwenCompatibilityError) as e:
            raise JiuwenSDKError(f"Jiuwen SDK 未安装: {e}") from e

    def optimize(
        self,
        prompt: str,
        feedback: str,
        mode: Literal["general", "insert", "select"] = "general",
        start_pos: Optional[int] = None,
        end_pos: Optional[int] = None,
        language: str = "zh",
    ) -> str:
        """
        调用 Jiuwen FeedbackPromptBuilder

        Raises:
            JiuwenSDKError: SDK 调用失败
        """
        self._ensure_available()

        logger.info(
            f"[jiuwen-adapter] mode={mode}, start_pos={start_pos}, end_pos={end_pos}"
        )

        request_config, client_config = build_jiuwen_model_configs(
            self.model_id, self.tenant_id
        )
        logger.info(
            f"[jiuwen-adapter] model_id={self.model_id}, tenant_id={self.tenant_id}, "
            f"api_base={client_config.api_base}, model={request_config.model_name}, "
            f"timeout={getattr(client_config, 'timeout', None)}, max_retries={getattr(client_config, 'max_retries', None)}"
        )
        FeedbackPromptBuilder, _ = _lazy_import_jiuwen_builders()

        builder = FeedbackPromptBuilder(
            model_config=request_config,
            model_client_config=client_config,
        )

        try:
            result = run_async(
                builder.build(
                    prompt=prompt,
                    feedback=feedback,
                    mode=mode,
                    start_pos=start_pos,
                    end_pos=end_pos,
                    language=normalize_language(language),
                )
            )
            if result is None:
                raise JiuwenSDKError("Jiuwen FeedbackPromptBuilder 返回为空")
            return _unwrap_prompt_response(str(result))
        except Exception as e:
            self.logger.error(f"Jiuwen FeedbackPromptBuilder 调用失败: {e}")
            raise JiuwenSDKError(f"优化调用失败: {e}") from e

    def optimize_badcase(
        self,
        prompt: str,
        bad_cases: List,
        language: str = "zh",
    ) -> str:
        """
        调用 Jiuwen BadCasePromptBuilder

        Raises:
            JiuwenSDKError: SDK 调用失败
        """
        self._ensure_available()

        _, BadCasePromptBuilder = _lazy_import_jiuwen_builders()

        request_config, client_config = build_jiuwen_model_configs(
            self.model_id, self.tenant_id
        )
        builder = BadCasePromptBuilder(
            model_config=request_config,
            model_client_config=client_config,
        )

        jiuwen_cases = [to_jiuwen_evaluated_case(bc) for bc in bad_cases]

        try:
            result = run_async(
                builder.build(
                    prompt=prompt,
                    cases=jiuwen_cases,
                    language=normalize_language(language),
                )
            )
            if result is None:
                raise JiuwenSDKError("Jiuwen BadCasePromptBuilder 返回为空")
            return _unwrap_prompt_response(str(result))
        except Exception as e:
            self.logger.error(f"Jiuwen BadCasePromptBuilder 调用失败: {e}")
            raise JiuwenSDKError(f"BadCasePromptBuilder 调用失败: {e}") from e

    def evaluate_semantic_consistency(
        self,
        *,
        question: str,
        expected_answer: str,
        model_answer: str,
        user_metrics: str = "",
    ) -> Tuple[float, str]:
        """LLM-as-judge semantic consistency scoring.

        Returns:
            (score, reason)

        Notes:
            openjiuwen 0.1.13 implements LLMAsJudgeMetric as a binary metric
            (1.0 pass / 0.0 fail) by parsing a JSON result from the judge model.
            ``metric.compute()`` only returns the numeric score; the actual judge
            verdict (with ``result`` and ``reason``) lives in the LLM response.
            We invoke the model directly here so we can extract **both** the score
            and the human-readable reason from the same response.
        """
        self._ensure_available()

        try:
            from openjiuwen.agent_evolving.evaluator.metrics.llm_as_judge import (
                LLMAsJudgeMetric,
            )
        except Exception as exc:
            raise JiuwenSDKError(f"Failed to import LLMAsJudgeMetric: {exc}") from exc

        request_config, client_config = build_jiuwen_model_configs(
            self.model_id, self.tenant_id
        )

        metric = LLMAsJudgeMetric(
            model_config=request_config,
            model_client_config=client_config,
            user_metrics=user_metrics or "",
        )

        # Build the same prompt that ``metric.compute()`` uses.
        messages = metric._template.format(
            {
                "question": str(question or ""),
                "expected_answer": str(expected_answer),
                "model_answer": str(model_answer),
            }
        ).to_messages()

        # Append a directive requiring Chinese output for the evaluation reason.
        # This ensures consistent Chinese language in the report regardless of
        # the judge model's default language.
        chinese_directive = (
            "\n\nIMPORTANT: You MUST respond in Chinese for the 'reason' field. "
            "The reason must be a clear explanation in Simplified Chinese. "
            "重要提示：'reason' 字段必须使用中文撰写，用简洁的中文解释评判结果。"
        )

        if messages:
            last = messages[-1]
            last_role = getattr(last, "role", None)
            # Default template returns a single UserMessage with role="user"
            if last_role == "user":
                last.content = (last.content or "") + chinese_directive
            else:
                # Append a new user message with the directive
                from openjiuwen.core.foundation.llm import UserMessage

                messages.append(UserMessage(content=chinese_directive.lstrip("\n")))

        try:
            response = asyncio.run(metric._model.invoke(messages)).content
        except Exception as exc:
            raise JiuwenSDKError(f"Judge LLM invoke failed: {exc}") from exc

        try:
            from openjiuwen.agent_evolving.utils import TuneUtils

            data = TuneUtils.parse_json_from_llm_response(response)
        except Exception as exc:
            raise JiuwenSDKError(f"Failed to parse judge response: {exc}") from exc

        if not isinstance(data, dict):
            raise JiuwenSDKError(f"Judge response is not a JSON object: {response!r}")

        result = data.get("result")
        if result is True or (
            isinstance(result, str) and result.strip().lower() == "true"
        ):
            score = 1.0
        else:
            score = 0.0

        raw_reason = data.get("reason")
        if isinstance(raw_reason, str):
            reason = raw_reason.strip()
        elif isinstance(raw_reason, dict):
            reason = raw_reason.get("reason") or ""
        else:
            reason = ""
        if not reason:
            reason = "通过" if score >= 1.0 else "失败"

        return score, reason

    def generate(self, **kwargs) -> dict:
        """调用 Jiuwen 提示词生成能力"""
        self._ensure_available()
        raise JiuwenSDKError("Jiuwen 提示词生成能力尚未实现")
