# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Migration reads legacy request fields without initializing inference clients."""

from copy import deepcopy

import pytest
from nexent.core.model_service.compatibility.legacy_reasoning import (
    legacy_reasoning_wire_parameters,
)


@pytest.mark.parametrize("enabled", [True, False])
def test_deepseek_explicit_toggle_uses_existing_thinking_object(enabled):
    extra = {"enable_thinking": enabled, "custom": {"flag": False}}
    before = deepcopy(extra)
    result = legacy_reasoning_wire_parameters(model_id="deepseek-chat", base_url="https://api.deepseek.com/v1",
        model_factory="deepseek", capability={"source": "models_dev", "status": "supported", "provider_id": "deepseek"},
        extra_body=extra)
    assert result == {"thinking": {"type": "enabled" if enabled else "disabled"}, "custom": {"flag": False}}
    assert extra == before


def test_alibaba_numeric_budget_keeps_legacy_priority_over_effort():
    result = legacy_reasoning_wire_parameters(model_id="qwen3.5-plus",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", model_factory="alibaba-cn",
        capability={"source": "models_dev", "status": "supported", "provider_id": "alibaba-cn",
                    "controls": [{"type": "budget_tokens"}]},
        effort="high", budget=64, extra_body={"enable_thinking": True})
    assert result == {"enable_thinking": True, "thinking_budget": 64}
    assert "reasoning_effort" not in result


def test_self_hosted_qwen_retains_old_chat_template_mapping():
    result = legacy_reasoning_wire_parameters(model_id="Qwen/ExactModel", base_url="https://custom.invalid/v1",
        model_factory="OpenAI-API-Compatible", extra_body={"enable_thinking": False,
            "chat_template_kwargs": {"custom": 0}})
    assert result == {"chat_template_kwargs": {"custom": 0, "enable_thinking": False}}


def test_custom_body_override_wins_exactly_as_in_openai_client_merge():
    result = legacy_reasoning_wire_parameters(model_id="custom", base_url="https://custom.invalid/v1",
        model_factory="custom", effort="high", extra_body={"reasoning_effort": "medium", "custom": [False, 0]})
    assert result == {"reasoning_effort": "medium", "custom": [False, 0]}


def test_export_does_not_allocate_http_clients_or_modify_input(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: pytest.fail("Migration must not allocate HTTP clients"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: pytest.fail("Migration must not allocate HTTP clients"))
    body = {"nested": {"values": [False, 0]}}
    result = legacy_reasoning_wire_parameters(model_id="custom", base_url="https://custom.invalid/v1",
        model_factory="custom", extra_body=body)
    result["nested"]["values"].append("changed")
    assert body == {"nested": {"values": [False, 0]}}
