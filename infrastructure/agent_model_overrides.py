# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Resolve and pin the provider body stored on an Agent version."""

import hmac
import json

from contracts.constants import environment


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
