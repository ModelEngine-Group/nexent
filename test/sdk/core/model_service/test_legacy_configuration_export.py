# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Old persisted values are interpreted by the same pure functions used by Agent construction."""

from copy import deepcopy

import pytest
from nexent.core.model_service.compatibility.legacy_config import legacy_agent_request_parameters


def test_export_preserves_null_sampling_custom_overrides_and_old_effort_selection():
    row = {"model_type": "llm", "base_url": "https://custom.invalid/v1", "model_factory": "custom",
           "temperature": None, "top_p": 0, "extra_params": {"enable_thinking": True,
           "reasoning_effort": "high", "__custom__": {"reasoning_effort": "medium", "flag": False}}}
    before = deepcopy(row)
    body = legacy_agent_request_parameters(row, model_id="exact", capability=None)
    assert body == {"temperature": None, "top_p": 0, "enable_thinking": True,
                    "reasoning_effort": "medium", "flag": False}
    assert row == before


def test_budget_range_uses_existing_clamp_and_alibaba_wire_mapping():
    row = {"model_type": "llm", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
           "model_factory": "dashscope", "temperature": 0.2, "top_p": None,
           "extra_params": {"enable_thinking": True, "reasoning_budget_tokens": 8}}
    capability = {"source": "models_dev", "status": "supported", "provider_id": "alibaba-cn",
                  "controls": [{"type": "budget_tokens", "min": 32, "max": 64}]}
    assert legacy_agent_request_parameters(row, model_id="qwen3.5-plus", capability=capability) == {
        "temperature": 0.2, "top_p": None, "enable_thinking": True, "thinking_budget": 32}
    assert row["extra_params"]["reasoning_budget_tokens"] == 8


def test_credential_columns_are_never_read_by_exporter():
    class Row(dict):
        def get(self, key, *args):
            assert key not in {"api_key", "access_token", "model_appid"}
            return super().get(key, *args)

    row = Row(model_type="llm", model_factory="custom", base_url="https://custom.invalid/v1", extra_params=None)
    assert legacy_agent_request_parameters(row, model_id="exact", capability=None) == {
        "temperature": None, "top_p": None}


@pytest.mark.parametrize("row", [{"model_type": "vlm"}, {"model_type": "embedding"},
                                {"model_type": "llm", "extra_params": []}])
def test_out_of_scope_or_invalid_records_are_rejected(row):
    with pytest.raises(ValueError):
        legacy_agent_request_parameters(row, model_id="exact", capability=None)
