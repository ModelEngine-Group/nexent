"""Governed model-level reasoning and prompt-cache capability catalog.

Rows are scoped to the actual ``model_factory`` used by Nexent.  A compatible
API alone is never evidence of feature support.  Bump ``CATALOG_REVISION`` when
changing behavior and keep official evidence links on every profile/rule.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple


CATALOG_REVISION = "2026-09-03.3"

OPENAI_MODEL_EVIDENCE = (
    "https://platform.openai.com/docs/models",
    "https://platform.openai.com/docs/guides/reasoning",
    "https://platform.openai.com/docs/guides/prompt-caching",
)
DASHSCOPE_REASONING_EVIDENCE = (
    "https://help.aliyun.com/en/model-studio/deep-thinking",
    "https://help.aliyun.com/en/model-studio/context-cache",
)
DEEPSEEK_EVIDENCE = (
    "https://api-docs.deepseek.com/guides/reasoning_model",
    "https://api-docs.deepseek.com/guides/kv_cache",
)
SILICONFLOW_EVIDENCE = (
    "https://docs.siliconflow.cn/en/api-reference/chat-completions/chat-completions",
    "https://docs.siliconflow.cn/en/userguide/capabilities/text-generation",
)


def _profile(
    version: str,
    *,
    reasoning: bool | None,
    reasoning_mode: str = "unknown",
    request_style: str = "unknown",
    efforts: tuple[str, ...] = (),
    default_effort: str | None = None,
    cache: bool | None,
    cache_mode: str = "unknown",
    cache_metrics: bool | None = None,
    evidence: tuple[str, ...],
) -> Dict[str, Any]:
    return {
        "profile_version": version,
        "reasoning": {
            "supported": reasoning,
            "mode": reasoning_mode,
            "request_style": request_style,
            "efforts": list(efforts),
            "default_effort": default_effort,
        },
        "prompt_cache": {
            "supported": cache,
            "mode": cache_mode,
            "metrics_available": cache_metrics,
        },
        "evidence": list(evidence),
    }


EXACT_CATALOG: Dict[Tuple[str, str], Dict[str, Any]] = {
    ("openai", "gpt-4o"): _profile(
        "openai/gpt-4o-features@1", reasoning=False, reasoning_mode="none",
        request_style="none", cache=True, cache_mode="openai_automatic",
        cache_metrics=True, evidence=OPENAI_MODEL_EVIDENCE,
    ),
    ("openai", "gpt-4.1"): _profile(
        "openai/gpt-4.1-features@1", reasoning=False, reasoning_mode="none",
        request_style="none", cache=True, cache_mode="openai_automatic",
        cache_metrics=True, evidence=OPENAI_MODEL_EVIDENCE,
    ),
    ("deepseek", "deepseek-chat"): _profile(
        "deepseek/deepseek-chat-features@1", reasoning=False, reasoning_mode="none",
        request_style="none", cache=True, cache_mode="provider_automatic",
        cache_metrics=True, evidence=DEEPSEEK_EVIDENCE,
    ),
    ("deepseek", "deepseek-reasoner"): _profile(
        "deepseek/deepseek-reasoner-features@1", reasoning=True,
        reasoning_mode="always", request_style="none", cache=True,
        cache_mode="provider_automatic", cache_metrics=True,
        evidence=DEEPSEEK_EVIDENCE,
    ),
    ("dashscope", "qwen-plus"): _profile(
        "dashscope/qwen-plus-features@1", reasoning=True,
        reasoning_mode="toggle", request_style="extra_body_enable_thinking",
        cache=True, cache_mode="provider_automatic", cache_metrics=True,
        evidence=DASHSCOPE_REASONING_EVIDENCE,
    ),
}


FAMILY_RULES = (
    {
        "provider": "openai",
        "pattern": r"(?:gpt-5(?:\.[0-9]+)?|o[134])(?:[-.].+)?",
        **_profile(
            "openai/reasoning-family@2", reasoning=True, reasoning_mode="effort",
            request_style="openai_reasoning_effort",
            efforts=("none", "minimal", "low", "medium", "high", "xhigh"),
            default_effort="medium",
            cache=True, cache_mode="openai_automatic", cache_metrics=True,
            evidence=OPENAI_MODEL_EVIDENCE,
        ),
    },
    {
        "provider": "openai",
        "pattern": r"gpt-(?:4\.1|4o)(?:[-.].+)?",
        **_profile(
            "openai/gpt4-nonreasoning-family@1", reasoning=False,
            reasoning_mode="none", request_style="none", cache=True,
            cache_mode="openai_automatic", cache_metrics=True,
            evidence=OPENAI_MODEL_EVIDENCE,
        ),
    },
    {
        "provider": "dashscope",
        "pattern": r"qwen3\.[5-8]-(?:max|plus|flash)(?:[-.].+)?",
        **_profile(
            "dashscope/qwen3-hybrid-family@2", reasoning=True,
            reasoning_mode="effort", request_style="openai_reasoning_effort",
            efforts=("none", "minimal", "low", "medium", "high", "xhigh", "max"),
            default_effort="medium",
            cache=True, cache_mode="provider_automatic", cache_metrics=True,
            evidence=DASHSCOPE_REASONING_EVIDENCE,
        ),
    },
    {
        "provider": "dashscope",
        "pattern": r"qwen3(?:[-.].*)?(?:thinking|a[0-9]+b)(?:[-.].*)?",
        **_profile(
            "dashscope/qwen3-thinking-family@1", reasoning=True,
            reasoning_mode="always", request_style="none", cache=True,
            cache_mode="provider_automatic", cache_metrics=True,
            evidence=DASHSCOPE_REASONING_EVIDENCE,
        ),
    },
    {
        "provider": "dashscope",
        "pattern": r"(?:deepseek-r1|deepseek-reasoner)(?:[-.].+)?",
        **_profile(
            "dashscope/deepseek-reasoning-family@1", reasoning=True,
            reasoning_mode="always", request_style="none", cache=True,
            cache_mode="provider_automatic", cache_metrics=True,
            evidence=DASHSCOPE_REASONING_EVIDENCE,
        ),
    },
    {
        "provider": "dashscope",
        "pattern": r"(?:deepseek-v3(?:\.[0-9]+)?|deepseek-v4-(?:flash|pro))(?:[-.].+)?",
        **_profile(
            "dashscope/deepseek-hybrid-family@1", reasoning=True,
            reasoning_mode="toggle", request_style="extra_body_enable_thinking",
            cache=True, cache_mode="provider_automatic", cache_metrics=True,
            evidence=DASHSCOPE_REASONING_EVIDENCE,
        ),
    },
    {
        "provider": "deepseek",
        "pattern": r"deepseek-(?:reasoner|r1)(?:[-.].+)?",
        **_profile(
            "deepseek/reasoning-family@1", reasoning=True,
            reasoning_mode="always", request_style="none", cache=True,
            cache_mode="provider_automatic", cache_metrics=True,
            evidence=DEEPSEEK_EVIDENCE,
        ),
    },
    {
        "provider": "deepseek",
        "pattern": r"deepseek-(?:chat|v3(?:\.[0-9]+)?|v4-(?:flash|pro))(?:[-.].+)?",
        **_profile(
            "deepseek/chat-family@1", reasoning=None, cache=True,
            cache_mode="provider_automatic", cache_metrics=True,
            evidence=DEEPSEEK_EVIDENCE,
        ),
    },
    {
        "provider": "silicon",
        "pattern": r"(?:Pro/)?deepseek-ai/(?:DeepSeek-R1|DeepSeek-Reasoner)(?:[-.].+)?",
        **_profile(
            "silicon/deepseek-reasoning-family@1", reasoning=True,
            reasoning_mode="always", request_style="none", cache=None,
            evidence=SILICONFLOW_EVIDENCE,
        ),
    },
    {
        "provider": "silicon",
        "pattern": r"(?:Pro/)?(?:Qwen/)?Qwen3(?:\.[5-8])?(?:[-/].+)?",
        "exclusions": (r".*(?:Instruct|Coder).*",),
        **_profile(
            "silicon/qwen3-thinking-family@1", reasoning=True,
            reasoning_mode="toggle", request_style="extra_body_enable_thinking",
            cache=None, evidence=SILICONFLOW_EVIDENCE,
        ),
    },
    {
        "provider": "silicon",
        "pattern": r"(?:Pro/)?(?:moonshotai/)?Kimi-K2(?:\.[0-9]+)?(?:[-.].+)?",
        **_profile(
            "silicon/kimi-k2-family@1", reasoning=None, cache=None,
            evidence=SILICONFLOW_EVIDENCE,
        ),
    },
    {
        "provider": "silicon",
        "pattern": r"(?:Pro/)?(?:MiniMaxAI/)?MiniMax-M[0-9](?:[-.].+)?",
        **_profile(
            "silicon/minimax-m-family@1", reasoning=None, cache=None,
            evidence=SILICONFLOW_EVIDENCE,
        ),
    },
    {
        "provider": "silicon",
        "pattern": r"(?:Pro/)?(?:zai-org/|THUDM/)?GLM[-.]?[0-9].*",
        **_profile(
            "silicon/glm-family-unknown@1", reasoning=None, cache=None,
            evidence=SILICONFLOW_EVIDENCE,
        ),
    },
    {
        "provider": "tokenpony",
        "pattern": r"(?:gpt-5(?:\.[0-9]+)?|o[134])(?:[-.].+)?",
        **_profile(
            "tokenpony/openai-reasoning-proxy-family@2", reasoning=True,
            reasoning_mode="effort", request_style="openai_reasoning_effort",
            efforts=("minimal", "low", "medium", "high"), default_effort="medium", cache=None,
            evidence=OPENAI_MODEL_EVIDENCE,
        ),
    },
    {
        "provider": "modelengine",
        "pattern": r"(?!)",
        **_profile(
            "modelengine/no-family-inference@1", reasoning=None, cache=None,
            evidence=("https://modelengine-ai.net",),
        ),
    },
)
