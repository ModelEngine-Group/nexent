# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Credential-bearing headers are separate from profile/body configuration."""

import pytest

from nexent.core.model_service.connection_headers import connection_headers


def test_header_authentication_without_api_key_and_detached_values():
    submitted = {"Authorization": "custom controlled credential", "X-Gateway": "test"}
    assert connection_headers(submitted) == {"authorization": "custom controlled credential", "x-gateway": "test"}
    assert "Authorization" in submitted


@pytest.mark.parametrize("headers", [
    {"Host": "wrong"}, {"Content-Type": "other"}, {"x-a": "line\nbreak"},
    {"x-a": "a", "X-A": "b"}, {"x a": "value"}, {"x-a": None}, {"x-a": "x" * 17000},
])
def test_invalid_headers_fail_without_echoing_values(headers):
    with pytest.raises(ValueError):
        connection_headers(headers)


def test_explicit_authorization_cannot_silently_replace_api_key():
    with pytest.raises(ValueError, match="MODEL_HTTP_AUTH_CONFLICT"):
        connection_headers({"Authorization": "custom credential"}, api_key="controlled-api-key")


def test_sender_injects_custom_headers_without_changing_body_or_snapshot(openai_profile):
    from nexent.core.model_service.adapters.openai_chat import OpenAIChatAdapter
    from nexent.core.model_service.contracts import ModelMessage, ModelRequest
    from nexent.core.model_service.profiles.contracts import VersionedReference
    from nexent.core.model_service.registry import AuthenticationRegistry

    profile = openai_profile.model_copy(update={"bindings": openai_profile.bindings.model_copy(update={
        "auth": VersionedReference(ref="bearer_token_v1", version=1)})})
    request = OpenAIChatAdapter().prepare_http_request(ModelRequest(request_id="header-test",
        outlet_id=profile.outlet_id, config_revision=profile.config_revision,
        messages=[ModelMessage(semantic_role="user")]), profile)
    sender = AuthenticationRegistry().sender_for(profile, lambda *_: "controlled-key",
        http_headers={"X-Gateway": "controlled-header"})
    assert sender._headers(request)["x-gateway"] == "controlled-header"
    assert sender._headers(request)["authorization"] == "Bearer controlled-key"
    assert "controlled-header" not in repr(profile.model_dump())
    assert "controlled-header" not in repr(request.json_body)
