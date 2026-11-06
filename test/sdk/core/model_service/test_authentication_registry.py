# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Auth registration and safe credential resolution, without network I/O."""

from dataclasses import replace

import pytest
from nexent.core.model_service.adapters.openai_chat import (
    ModelAdapterError,
    OpenAIChatAdapter,
)
from nexent.core.model_service.contracts import ModelMessage, ModelRequest
from nexent.core.model_service.http_contracts import ModelTransportError
from nexent.core.model_service.registry import AuthenticationRegistry


class CredentialStore:
    def lookup(self, tenant_id, reference):
        raise AssertionError("External store must be mocked")


@pytest.fixture
def lookup(mocker):
    return mocker.patch.object(CredentialStore, "lookup", return_value="dummy-secret")


def configured(profile, auth="bearer_token_v1", version=1, kind="model_record"):
    values = profile.model_dump()
    values["outlet_id"] = 7
    values["connection"]["credential_ref"]["model_id"] = 7
    values["bindings"]["auth"] = {"ref": auth, "version": version}
    values["connection"]["credential_ref"]["kind"] = kind
    values["connection_rules"]["credential_kind"] = kind
    return type(profile).model_validate(values)


def prepared(profile):
    return OpenAIChatAdapter().prepare_http_request(
        ModelRequest(
            request_id="request",
            outlet_id=profile.outlet_id,
            config_revision=profile.config_revision,
            messages=[ModelMessage(semantic_role="user", content_parts=[{"type": "text", "text": "hi"}])],
        ),
        profile,
    )


def test_bearer_reads_tenant_reference_once_and_freezes_headers(openai_profile, lookup):
    profile = configured(openai_profile)
    sender = AuthenticationRegistry().sender_for(profile, lookup)
    request = prepared(profile)
    lookup.assert_not_called()
    frozen = sender.freeze_credentials(request)
    lookup.assert_called_once_with("tenant", profile.connection.credential_ref)
    lookup.return_value = "changed-secret"
    for _ in range(3):
        assert frozen._headers(request)["authorization"] == "Bearer dummy-secret"
    lookup.assert_called_once()


def test_no_auth_never_reads_credentials(openai_profile, lookup):
    profile = configured(openai_profile, auth="no_auth_v1", kind="none")
    lookup.side_effect = AssertionError("Must not read credentials")
    sender = AuthenticationRegistry().sender_for(profile, lookup)
    assert sender._headers(prepared(profile)) == {"content-type": "application/json"}
    lookup.assert_not_called()


@pytest.mark.parametrize("auth,version", [("unregistered", 1), ("bearer_token_v1", 2)])
def test_unknown_auth_reference_rejected_before_lookup(openai_profile, lookup, auth, version):
    with pytest.raises(ModelAdapterError, match="^MODEL_AUTH_UNREGISTERED$"):
        AuthenticationRegistry().sender_for(configured(openai_profile, auth, version), lookup)
    lookup.assert_not_called()


@pytest.mark.parametrize("value", [None, "", "  ", "dummy\r\nInjected: header", "dummy\x00", "非ASCII"])
def test_invalid_credentials_are_rejected_without_echo(openai_profile, lookup, value):
    profile = configured(openai_profile)
    lookup.return_value = value
    sender = AuthenticationRegistry().sender_for(profile, lookup)
    with pytest.raises(ModelTransportError, match="^CREDENTIAL_RESOLUTION_FAILED$") as caught:
        sender.freeze_credentials(prepared(profile))
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("auth,kind", [("bearer_token_v1", "none"), ("no_auth_v1", "model_record")])
def test_auth_scheme_cannot_use_other_credential_kind(openai_profile, lookup, auth, kind):
    profile = configured(openai_profile, auth=auth, kind=kind)
    with pytest.raises(ModelTransportError, match="^CREDENTIAL_RESOLUTION_FAILED$"):
        AuthenticationRegistry().sender_for(profile, lookup).freeze_credentials(prepared(profile))
    lookup.assert_not_called()


def test_lookup_exception_is_sanitized(openai_profile, lookup):
    profile = configured(openai_profile)
    lookup.side_effect = RuntimeError("dummy-private-value")
    with pytest.raises(ModelTransportError, match="^CREDENTIAL_RESOLUTION_FAILED$") as caught:
        AuthenticationRegistry().sender_for(profile, lookup).freeze_credentials(prepared(profile))
    assert caught.value.__cause__ is None


def test_sender_cannot_read_another_outlet_credential(openai_profile, lookup):
    profile = configured(openai_profile)
    sender = AuthenticationRegistry().sender_for(profile, lookup)
    request = prepared(profile)
    foreign = replace(
        request,
        json_body={},
        headers=dict(request.headers),
        credential_ref=type(request.credential_ref)(kind="model_record", model_id=8),
    )
    with pytest.raises(ModelTransportError, match="^CREDENTIAL_RESOLUTION_FAILED$"):
        sender.freeze_credentials(foreign)
    lookup.assert_not_called()


def test_registry_lists_only_implemented_auth_schemes():
    assert {(item.ref, item.version) for item in AuthenticationRegistry().references} == {
        ("bearer_token_v1", 1), ("no_auth_v1", 1)
    }
