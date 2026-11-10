# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Resolve and pin the provider body stored on an Agent version."""

import hmac
import json
import math
from typing import Any

from nexent.core.agents.agent_model import ModelConfig

from contracts.constants import environment
from contracts.errors.exceptions import RunModelControlsError
from infrastructure.model_reasoning import reasoning_controls


def merge_provider_body(default: dict | None, extra_params: dict) -> dict | None:
    merged = dict(default or {})
    for key, value in extra_params.items():
        if key in {"enable_thinking", "reasoning_effort", "reasoning_budget_tokens"}:
            continue
        if key == "__custom__" and isinstance(value, dict):
            for name, custom in value.items():
                if custom is None:
                    merged.pop(name, None)
                else:
                    merged[name] = custom
        else:
            merged[key] = value
    return merged or None


def get_provider_body_patch(overrides: dict | None, model_id: int) -> dict | None:
    entry = (overrides or {}).get(str(model_id))
    patch = entry.get("extra_params") if isinstance(entry, dict) else None
    return patch if isinstance(patch, dict) and patch else None


def provider_body_revision(scope: tuple[str, int, int, int], body: dict | None) -> str:
    if not environment.JWT_SECRET:
        raise ValueError("AgentOS signing is not configured")
    key = hmac.digest(environment.JWT_SECRET.encode(), b"nexent/agentos/provider-body/v1", "sha256")
    payload = json.dumps([scope, body], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.digest(key, payload, "sha256").hex()


def overlay_root_model(base: ModelConfig, values: dict[str, Any], alias: str) -> ModelConfig:
    """Apply only present fields and validate active effort/budget intent."""
    root = base.model_copy(deep=True)
    root.cite_name = alias
    explicit_sampling = []
    for key, maximum in (("temperature", 2), ("top_p", 1)):
        value = values.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= maximum:
            raise RunModelControlsError("model_controls_invalid")
        explicit_sampling.append(key)
        setattr(root, key, value)
    if explicit_sampling:
        root.explicit_sampling = explicit_sampling
        # OpenAI's extra_body can otherwise shadow the canonical keyword values.
        root.extra_body = {k: v for k, v in (root.extra_body or {}).items() if k not in explicit_sampling} or None
    if not any(k in values for k in ("deep_thinking", "thinking_effort", "reasoning_budget_tokens")):
        return root
    enabled = values.get("deep_thinking", base.enable_thinking)
    effort = values.get("thinking_effort")
    budget = values.get("reasoning_budget_tokens")
    controls = reasoning_controls(base.reasoning_capability)
    effort_control = next((c for c in controls if c.get("type") == "effort"), None)
    budget_control = next((c for c in controls if c.get("type") == "budget_tokens"), None)
    if enabled:
        if not controls:
            raise RunModelControlsError("model_controls_invalid")
        if effort not in (None, "auto") and budget not in (None, 0):
            raise RunModelControlsError("model_controls_invalid")
        if effort not in (None, "auto"):
            if not effort_control or effort not in effort_control.get("values", []):
                raise RunModelControlsError("model_controls_invalid")
            root.reasoning_effort = effort
            root.reasoning_budget_tokens = None
        elif effort == "auto":
            # Resolve against the immutable model/Agent defaults, never last turn.
            root.reasoning_effort = base.reasoning_effort
        if budget is not None:
            if not budget_control or (budget > 0 and not budget_control["min"] <= budget <= budget_control["max"]):
                raise RunModelControlsError("model_controls_invalid")
            root.reasoning_budget_tokens = budget or base.reasoning_budget_tokens
            root.reasoning_effort = None
        elif budget_control and effort == "auto":
            root.reasoning_effort = None
    else:
        root.reasoning_effort = None
        root.reasoning_budget_tokens = None
    if "deep_thinking" in values:
        root.enable_thinking = enabled
    extra = dict(root.extra_body or {})
    if "deep_thinking" in values:
        extra["enable_thinking"] = enabled
    if any(k in values for k in ("deep_thinking", "thinking_effort", "reasoning_budget_tokens")):
        extra.pop("reasoning_effort", None)
        extra.pop("reasoning_budget_tokens", None)
    root.extra_body = extra or None
    return root
