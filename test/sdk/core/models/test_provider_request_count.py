from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx

from nexent.core.models.final_request_budget import build_final_request_shape
from nexent.core.models.provider_request_count import count_final_request, endpoint_fingerprint


BASE = "https://example.test/v1"


def _metadata(**overrides):
    value = {
        "status": "supported",
        "adapter_version": "1.0.0",
        "selected_protocol": "openai_responses",
        "endpoint_fingerprint": endpoint_fingerprint(BASE),
        "model_identity": "dashscope:qwen",
        "stale_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "capabilities": {"text": "supported", "tools": "unknown", "media": "unknown"},
    }
    value.update(overrides)
    return value


def test_ac_p2_003_provider_count_precedence_for_matching_text_shape():
    shape = build_final_request_shape({"model": "qwen", "messages": [{"role": "user", "content": "hello"}]})
    response = MagicMock(status_code=200, content=b'{"input_tokens": 17}')
    response.json.return_value = {"input_tokens": 17}
    client = MagicMock()
    client.__enter__.return_value.post.return_value = response
    with patch("nexent.core.models.provider_request_count.httpx.Client", return_value=client) as client_type:
        count, reason = count_final_request(
            shape,
            metadata=_metadata(),
            base_url=BASE,
            api_key="secret",
            model_name="qwen",
            canonical_model_id="dashscope:qwen",
        )
    assert (count, reason) == (17, None)
    assert client_type.call_args.kwargs["follow_redirects"] is False
    assert client.__enter__.return_value.post.call_args.kwargs["json"]["input"] == [
        {"content": "hello", "role": "user"}
    ]


def test_ac_p2_003_text_capability_does_not_authorize_tools_shape():
    shape = build_final_request_shape({"messages": [], "tools": [{"type": "function"}]})
    count, reason = count_final_request(
        shape,
        metadata=_metadata(),
        base_url=BASE,
        api_key="secret",
        model_name="qwen",
        canonical_model_id="dashscope:qwen",
    )
    assert count is None
    assert reason == "count_capability_shape_unsupported"


def test_ac_p2_003_text_capability_does_not_authorize_reasoning_template():
    shape = build_final_request_shape(
        {
            "messages": [],
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        }
    )
    count, reason = count_final_request(
        shape,
        metadata=_metadata(),
        base_url=BASE,
        api_key="secret",
        model_name="qwen",
        canonical_model_id="dashscope:qwen",
    )
    assert count is None
    assert reason == "count_capability_shape_unsupported"


def test_ac_p2_003_temporary_count_failure_falls_back_with_reason():
    shape = build_final_request_shape({"messages": []})
    with patch(
        "nexent.core.models.provider_request_count.httpx.Client",
        side_effect=httpx.ReadTimeout("late"),
    ):
        count, reason = count_final_request(
            shape,
            metadata=_metadata(),
            base_url=BASE,
            api_key="secret",
            model_name="qwen",
            canonical_model_id="dashscope:qwen",
        )
    assert (count, reason) == (None, "count_timeout")


def test_ac_p2_003_stale_or_cross_model_capability_is_not_used():
    shape = build_final_request_shape({"messages": []})
    count, reason = count_final_request(
        shape,
        metadata=_metadata(model_identity="other:model"),
        base_url=BASE,
        api_key="secret",
        model_name="qwen",
        canonical_model_id="dashscope:qwen",
    )
    assert count is None
    assert reason == "count_capability_model_mismatch"


def test_ac_p2_003_runtime_count_rejects_credentialed_or_queried_base_url():
    shape = build_final_request_shape({"messages": []})
    count, reason = count_final_request(
        shape,
        metadata=_metadata(),
        base_url="https://user@example.test/v1?redirect=evil",
        api_key="secret",
        model_name="qwen",
        canonical_model_id="dashscope:qwen",
    )
    assert count is None
    assert reason == "count_ssrf_rejected"
