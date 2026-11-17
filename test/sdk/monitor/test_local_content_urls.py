# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Local payloads retain resource locations while removing URL credentials."""

import copy
import json
from urllib.parse import parse_qs, quote, urlsplit

import pytest
from nexent.monitor.local_content import safe_local_content


@pytest.mark.parametrize(
    "key",
    [
        "X-Amz-Signature", "X-Amz-Credential", "X-Amz-Security-Token",
        "AWSAccessKeyId", "Signature", "SecurityToken", "X-Goog-Signature",
        "X-Goog-Credential", "GoogleAccessId", "OSSAccessKeyId", "x-oss-signature",
        "x-oss-credential", "sig", "access_token", "api_key", "token",
    ],
)
def test_url_credentials_are_redacted_without_changing_business_parameters(key):
    original = f"https://storage.example/bucket/report.pdf?version=7&{key}=synthetic-secret&part=2#page=3"
    value = safe_local_content(original)
    assert "synthetic-secret" not in value
    assert "REDACTED_CREDENTIAL" in value
    parsed = urlsplit(value)
    assert parsed.netloc == "storage.example" and parsed.path == "/bucket/report.pdf"
    assert parse_qs(parsed.query)["version"] == ["7"]
    assert parse_qs(parsed.query)["part"] == ["2"] and parsed.fragment == "page=3"
    assert "synthetic-secret" in original


def test_embedded_urls_in_messages_and_tool_results_are_detached_and_safe():
    url = "https://storage.example/report?X-Amz-Signature=synthetic-secret&version=7"
    original = {"messages": [{"content": f"请读取 [报告]({url})，完成后回答。"}],
                "tool_result": {"url": url, "title": "报告"}}
    before = copy.deepcopy(original)
    result = json.loads(safe_local_content(original))
    assert original == before
    assert "synthetic-secret" not in json.dumps(result)
    assert "报告](https://storage.example/report?" in result["messages"][0]["content"]
    assert ")，完成后回答。" in result["messages"][0]["content"]
    assert result["tool_result"]["title"] == "报告"


def test_percent_encoded_proxy_target_and_encoded_parameter_names_are_sanitized():
    nested = "https://storage.example/a?X-Amz-%53ignature=synthetic-secret&part=2"
    original = "https://nexent.example/api/file/fetch?presigned_url=" + quote(nested, safe="") + "&download=1"
    value = safe_local_content(original)
    outer = parse_qs(urlsplit(value).query)
    assert outer["download"] == ["1"]
    assert "synthetic-secret" not in outer["presigned_url"][0]
    assert parse_qs(urlsplit(outer["presigned_url"][0]).query)["part"] == ["2"]


def test_url_userinfo_and_fragment_tokens_are_redacted():
    result = safe_local_content("https://synthetic-user:synthetic-password@example.test/report#access_token=synthetic-token")
    assert all(secret not in result for secret in ("synthetic-user", "synthetic-password", "synthetic-token"))
    assert urlsplit(result).hostname == "example.test"
    assert result.count("REDACTED_CREDENTIAL") == 2


@pytest.mark.parametrize("text", [
    "ordinary text: token=business-value",
    "https://example.test/report?version=a%2Fb&name=%E6%8A%A5%E5%91%8A#page=2",
    "请阅读 https://example.test/docs?q=接口 ，然后回答。",
    "s3://bucket/report.pdf",
    "data:image/png;base64,synthetic-content",
])
def test_safe_content_without_url_credentials_is_preserved_exactly(text):
    assert safe_local_content(text) == text


def test_physical_request_snapshot_uses_same_url_policy_without_mutating_wire_body():
    from nexent.monitor.model_attempt import _safe

    request = {"messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "https://storage.example/image?sig=synthetic-secret"}},
    ]}]}
    before = copy.deepcopy(request)
    result = _safe(request)
    assert request == before
    assert "synthetic-secret" not in json.dumps(result)
    assert "REDACTED_CREDENTIAL" in json.dumps(result)


def test_url_redaction_is_idempotent_and_supports_ipv6_and_duplicate_query_keys():
    original = "https://[::1]/report?SIG=first-secret&sig=second-secret&name=报告"
    value = safe_local_content(original)
    assert "first-secret" not in value and "second-secret" not in value
    assert urlsplit(value).hostname == "::1" and "name=报告" in value
    assert safe_local_content(value) == value


@pytest.mark.parametrize("depth", [8, 9])
def test_encoded_proxy_nesting_has_a_finite_budget(depth):
    url = "https://storage.example/report?sig=synthetic-secret"
    for _ in range(depth):
        url = "https://proxy.example/fetch?url=" + quote(url, safe="")
    if depth == 9:
        with pytest.raises(ValueError, match="URL nesting"):
            safe_local_content(url)
    else:
        assert "synthetic-secret" not in safe_local_content(url)
