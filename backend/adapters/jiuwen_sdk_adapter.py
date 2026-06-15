"""
openjiuwen SDK adapter for Nexent.

This module must be imported lazily (not at module load time) because
openjiuwen 0.1.13 has circular import bugs in its __init__.py files that
prevent the SDK from loading unless we bypass them.

Import flow:
  backend/adapters/__init__.py -> try/except -> JiuwenSDKAdapter = None
  -> when needed: _install_jiuwen_bypasser() -> openjiuwen imports work
"""
import asyncio
import importlib.abc
import importlib.machinery
import json
import logging
import os
import sys
import types
from typing import Any, List, Literal, Optional, Tuple

from openjiuwen.dev_tools.tune.base import Case as _Case, EvaluatedCase as _EvaluatedCase


def _case_from_inputs_label(inputs: dict, label: dict) -> "_Case":
    # Keep stable keys for schema; allow extra fields to exist.
    return _Case(inputs=inputs, label=label)


def _extract_score_reason(evaluated: Any) -> Tuple[float, str]:
    """Try to normalize Jiuwen EvaluatedCase into (score, reason)."""
    try:
        score = float(getattr(evaluated, "score", 0.0) or 0.0)
    except Exception:
        score = 0.0
    reason = getattr(evaluated, "reason", "") or ""
    return score, str(reason)

logger = logging.getLogger("jiuwen_adapter")

from adapters.exception import JiuwenSDKError


# ----------------------------------------------------------------------
# Circular import bypasser for openjiuwen 0.1.13
#
# openjiuwen has broken __init__.py files that create circular import chains:
#   tune/__init__.py -> tune.optimizer -> core.operator -> agent_evolving -> ...
# This bypasser prevents those __init__.py files from executing while still
# allowing regular .py submodule files to load normally.
# ----------------------------------------------------------------------
_CIRCULAR_CHAIN = {
    "openjiuwen.agent_evolving",
    "openjiuwen.agent_evolving.trainer",
    "openjiuwen.agent_evolving.trainer.trainer",
    "openjiuwen.agent_evolving.trainer.progress",
    "openjiuwen.core",
    "openjiuwen.dev_tools",
    "openjiuwen.dev_tools.tune",
    "openjiuwen.dev_tools.tune.optimizer",
    "openjiuwen.dev_tools.tune.optimizer.instruction_optimizer",
    "openjiuwen.dev_tools.prompt_builder",
    "openjiuwen.dev_tools.prompt_builder.builder",
}


class _JiuwenInitBypasser(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """
    Meta path finder that intercepts __init__.py loading within openjiuwen,
    blocking only the packages in the circular import chain while letting
    all other modules (including base.py files) load normally.
    """

    def find_spec(self, fullname: str, path: Any, target: Any = None) -> Any:
        if not fullname.startswith("openjiuwen") or fullname == "openjiuwen":
            return None

        try:
            import openjiuwen as _oj

            pkg_root = _oj.__path__[0]
        except ImportError:
            return None

        parts = fullname.split(".")[1:]
        file_path = pkg_root
        for p in parts:
            file_path = os.path.join(file_path, p)

        is_package = os.path.isdir(file_path)
        if not is_package:
            return None

        init_path = os.path.join(file_path, "__init__.py")
        if not os.path.exists(init_path):
            return None

        if fullname not in _CIRCULAR_CHAIN:
            return None

        spec = importlib.machinery.ModuleSpec(
            fullname, self, is_package=True, origin="<init bypassed>"
        )
        spec.submodule_search_locations = [file_path]
        return spec

    def create_module(self, module: Any) -> None:
        return None

    def exec_module(self, module: Any) -> None:
        import openjiuwen as _oj

        pkg_root = _oj.__path__[0]
        parts = module.__name__.split(".")[1:]
        file_path = pkg_root
        for p in parts:
            file_path = os.path.join(file_path, p)
        module.__path__ = [file_path]
        module.__file__ = os.path.join(file_path, "__init__.py")

    def __getattr__(self, name: str) -> Any:
        """Handle special attributes like find_distributions to prevent recursion."""
        import openjiuwen as _oj
        import importlib

        # Prevent recursion when Python scans sys.meta_path for find_distributions etc.
        if name in (
            "find_distributions",
            "find_module",
            "__path__",
            "__name__",
            "__file__",
            "__loader__",
            "__package__",
            "__spec__",
        ):
            raise AttributeError(name)

        pkg_root = _oj.__path__[0]
        parts = self.__name__.split(".")[1:] + [name]
        file_path = pkg_root
        for p in parts:
            file_path = os.path.join(file_path, p)

        # If it's a package directory, import it as a submodule
        if os.path.isdir(file_path) and os.path.exists(os.path.join(file_path, "__init__.py")):
            return importlib.import_module(f"{self.__name__}.{name}")
        # If it's a regular .py file
        if os.path.exists(file_path + ".py"):
            return importlib.import_module(f"{self.__name__}.{name}")
        raise AttributeError(name)


_bypasser_installed = False


def _install_jiuwen_bypasser() -> bool:
    """
    Install the circular import bypasser for openjiuwen.
    Returns True if installed, False if already installed or openjiuwen not available.
    """
    global _bypasser_installed
    if _bypasser_installed:
        return True

    # Stub missing optional dependencies before openjiuwen import chain reaches them
    _stubbed = [
        ("pymilvus", {"is_successful": lambda *args, **kwargs: True}),
        ("dashscope", {}),
        ("pdfplumber", {}),
    ]
    for _name, _attrs in _stubbed:
        if _name not in sys.modules:
            _mod = types.ModuleType(_name)
            for _k, _v in _attrs.items():
                setattr(_mod, _k, _v)
            sys.modules[_name] = _mod
            _mod.__path__ = []

    # Pre-create nested stub modules for pymilvus.client.utils chain
    if "pymilvus.client" not in sys.modules:
        _client_mod = types.ModuleType("pymilvus.client")
        _client_mod.__path__ = []
        sys.modules["pymilvus.client"] = _client_mod
    if "pymilvus.client.utils" not in sys.modules:
        _utils_mod = types.ModuleType("pymilvus.client.utils")
        _utils_mod.is_successful = lambda *args, **kwargs: True
        sys.modules["pymilvus.client.utils"] = _utils_mod

    # Stub dashscope sub-modules that may be imported lazily
    _dashscope_subs = [
        ("dashscope.api_entities", {}),
        ("dashscope.api_entities.data", {}),
        ("dashscope.api_entities.dashscope_response", {"DashScopeAPIResponse": object}),
        ("dashscope.common", {"REQUEST_TIMEOUT_KEYWORD": "timeout"}),
        ("dashscope.common.constants", {"REQUEST_TIMEOUT_KEYWORD": "timeout"}),
    ]
    for _name, _attrs in _dashscope_subs:
        if _name not in sys.modules:
            _m = types.ModuleType(_name)
            _m.__path__ = []
            for _k, _v in _attrs.items():
                setattr(_m, _k, _v)
            sys.modules[_name] = _m

    try:
        import openjiuwen  # noqa: F401
    except ImportError:
        return False

    for finder in sys.meta_path:
        if isinstance(finder, _JiuwenInitBypasser):
            _bypasser_installed = True
            return True

    sys.meta_path.insert(0, _JiuwenInitBypasser())
    _bypasser_installed = True
    return True


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
    _install_jiuwen_bypasser()

    try:
        import openjiuwen  # noqa: F401
    except ImportError as e:
        raise JiuwenSDKError(f"Jiuwen SDK 未安装: {e}") from e

    from openjiuwen.core.foundation.llm.schema.config import (
        ModelRequestConfig,
        ModelClientConfig,
        ProviderType,
    )
    # Optional: allow adjusting SDK internal client timeout via config if supported.
    # We keep import local to avoid breaking on SDK version differences.
    try:
        from openjiuwen.core.foundation.llm import ModelClientOptions  # type: ignore
    except Exception:  # pragma: no cover
        ModelClientOptions = None  # type: ignore
    from openjiuwen.dev_tools.prompt_builder.builder.feedback_prompt_builder import (
        FeedbackPromptBuilder,
    )
    from openjiuwen.dev_tools.prompt_builder.builder.badcase_prompt_builder import (
        BadCasePromptBuilder,
    )
    from openjiuwen.dev_tools.tune.base import Case, EvaluatedCase

    # Evaluator metrics (avoid importing openjiuwen.dev_tools.tune package root)
    from openjiuwen.agent_evolving.evaluator.metrics.llm_as_judge import LLMAsJudgeMetric

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

    ModelRequestConfig, ModelClientConfig, ProviderType, _, _, _, _, _ = _lazy_import_jiuwen()

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
    if ssl_verify and not ssl_cert:
        ssl_verify = False

    client_config = ModelClientConfig(
        client_provider=ProviderType.OpenAI,
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


def _build_openai_client(
    client_config: "ModelClientConfig", request_config: "ModelRequestConfig"
) -> Any:
    """
    直接创建 OpenAIModelClient，绕过 FeedbackPromptBuilder 的深导入链。
    """
    _install_jiuwen_bypasser()
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
    _install_jiuwen_bypasser()

    try:
        import openjiuwen  # noqa: F401
    except ImportError as e:
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
                text = text[len(fence):]
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
        if not _bypasser_installed:
            _install_jiuwen_bypasser()

        try:
            import openjiuwen  # noqa: F401
        except ImportError as e:
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

        logger.info(f"[jiuwen-adapter] mode={mode}, start_pos={start_pos}, end_pos={end_pos}")

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
        """
        self._ensure_available()

        try:
            _, _, _, _, _, _, _, LLMAsJudgeMetric = _lazy_import_jiuwen()
        except Exception as exc:
            raise JiuwenSDKError(f"Failed to import LLMAsJudgeMetric: {exc}") from exc

        request_config, client_config = build_jiuwen_model_configs(self.model_id, self.tenant_id)

        metric = LLMAsJudgeMetric(
            model_config=request_config,
            model_client_config=client_config,
            user_metrics=user_metrics or "",
        )

        try:
            score = float(
                metric.compute(
                    prediction=model_answer,
                    label=expected_answer,
                    question=question,
                )
            )
        except Exception as exc:
            raise JiuwenSDKError(f"LLMAsJudgeMetric compute failed: {exc}") from exc

        reason = "pass" if score >= 1.0 else "fail"
        return score, reason

    def generate(self, **kwargs) -> dict:
        """调用 Jiuwen 提示词生成能力"""
        self._ensure_available()
        raise JiuwenSDKError("Jiuwen 提示词生成能力尚未实现")
