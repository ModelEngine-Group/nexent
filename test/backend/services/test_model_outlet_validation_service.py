# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Connection probes capture configuration once and preserve revision/cancellation boundaries."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from contracts.errors.exceptions import ModelOutletConflictError
from contracts.model import ModelOutletCreateRequest, ModelOutletValidationRequest
from nexent.core.model_service.contracts import AssistantMessage, ModelError, ModelEvent
from nexent.core.model_service.service import ModelServiceError
from management.services.model.profiles import build_outlet_draft, validate_model_outlet

from test.backend.services.test_model_profile_service import draft_request, outlet_database  # noqa: F401


@pytest.fixture
def probe(monkeypatch, outlet_database):
    import nexent.core.concurrency as concurrency
    import nexent.core.model_service.service as model_service
    import management.services.model.profiles as service

    profile, _ = build_outlet_draft(draft_request(parameter_values={"enable_thinking": False}), "tenant")
    data = profile.model_dump()
    data["outlet_id"] = data["connection"]["credential_ref"]["model_id"] = 42
    profile = profile.__class__.model_validate(data)
    loader = Mock(return_value=(profile, "controlled-key", {}))
    monkeypatch.setattr(service, "_load_validation_outlet", loader)

    async def run(_name, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(concurrency, "run_blocking", run)
    invoke = AsyncMock(return_value=AssistantMessage(content_parts=[{"type": "text", "text": "Hello"}],
                                                    finish_reason="stop"))

    @asynccontextmanager
    async def stream(_service, call, captured):
        async def events():
            try:
                message = await invoke(call, captured)
            except ModelServiceError as failure:
                yield ModelEvent(request_id=failure.error.request_id, message_id=uuid4(), sequence=1,
                                 type="error", error=failure.error)
                return
            if message is not None:
                yield ModelEvent(request_id=call.request_id, message_id=message.message_id, sequence=1,
                                 type="message_completed", message=message, finish_reason=message.finish_reason)
        iterator = events()
        try:
            yield iterator
        finally:
            await iterator.aclose()

    monkeypatch.setattr(model_service.ModelService, "astream", stream)
    db, _ = outlet_database
    db.update_model_outlet_connectivity = Mock()
    return profile, loader, invoke, db.update_model_outlet_connectivity


@pytest.mark.asyncio
async def test_saved_probe_uses_captured_parameters_and_revision(probe):
    profile, loader, invoke, update = probe
    result = await validate_model_outlet(ModelOutletValidationRequest(outlet_id=42, expected_revision=1), "tenant")
    assert result["ok"] is True and result["check_scope"] == "connection_only"
    loader.assert_called_once_with(42, "tenant")
    call, captured = invoke.call_args.args
    assert captured is profile and captured.parameter_values == {"enable_thinking": False}
    assert call.tools == [] and call.stream is True and call.purpose == "connection_validation"
    assert call.messages[0].semantic_role == "user"
    assert call.messages[0].content_parts == [{"type": "text", "text": "Hello"}]
    update.assert_called_once_with(42, "tenant", 1, "available")
    assert "controlled-key" not in repr(result)


@pytest.mark.asyncio
async def test_draft_probe_does_not_load_or_write_saved_status(probe):
    _, loader, invoke, update = probe
    draft = ModelOutletCreateRequest(**draft_request().model_dump(), api_key="controlled-key")
    result = await validate_model_outlet(ModelOutletValidationRequest(draft=draft), "tenant")
    assert result["ok"] is True and result["model_id"] is None
    loader.assert_not_called()
    update.assert_not_called()
    assert invoke.call_args.args[1].identity.tenant_id == "tenant"


@pytest.mark.asyncio
async def test_stale_or_missing_record_does_not_send_request(probe):
    _, loader, invoke, update = probe
    with pytest.raises(ModelOutletConflictError):
        await validate_model_outlet(ModelOutletValidationRequest(outlet_id=42, expected_revision=2), "tenant")
    loader.side_effect = LookupError("MODEL_OUTLET_NOT_FOUND")
    with pytest.raises(LookupError):
        await validate_model_outlet(ModelOutletValidationRequest(outlet_id=42), "other")
    invoke.assert_not_awaited()
    update.assert_not_called()


@pytest.mark.asyncio
async def test_empty_response_is_unavailable(probe):
    _, _, invoke, update = probe
    invoke.return_value = AssistantMessage(finish_reason="stop")
    result = await validate_model_outlet(ModelOutletValidationRequest(outlet_id=42), "tenant")
    assert result["ok"] is False and result["error"]["category"] == "MODEL_EMPTY_RESPONSE"
    update.assert_called_once_with(42, "tenant", 1, "unavailable")


@pytest.mark.asyncio
async def test_normalized_provider_failure_is_returned_without_raw_payload(probe):
    _, _, invoke, update = probe
    invoke.side_effect = ModelServiceError(ModelError(category="AUTHENTICATION_ERROR", scope="provider",
        retryable=False, safe_message="Model authentication failed", request_id="test"))
    result = await validate_model_outlet(ModelOutletValidationRequest(outlet_id=42), "tenant")
    assert result["ok"] is False and result["error"]["category"] == "AUTHENTICATION_ERROR"
    update.assert_called_once_with(42, "tenant", 1, "unavailable")


@pytest.mark.asyncio
async def test_cancelled_probe_never_writes_status(probe):
    _, _, invoke, update = probe
    invoke.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await validate_model_outlet(ModelOutletValidationRequest(outlet_id=42), "tenant")
    update.assert_not_called()


@pytest.mark.asyncio
async def test_configuration_change_during_probe_rejects_late_status(probe):
    _, _, invoke, update = probe
    update.side_effect = ModelOutletConflictError()
    with pytest.raises(ModelOutletConflictError):
        await validate_model_outlet(ModelOutletValidationRequest(outlet_id=42, expected_revision=1), "tenant")
    invoke.assert_awaited_once()
    update.assert_called_once_with(42, "tenant", 1, "available")


@pytest.mark.asyncio
async def test_stream_without_completion_is_unavailable(probe):
    _, _, invoke, update = probe
    invoke.return_value = None
    result = await validate_model_outlet(ModelOutletValidationRequest(outlet_id=42), "tenant")
    assert result["ok"] is False
    update.assert_called_once_with(42, "tenant", 1, "unavailable")


@pytest.mark.asyncio
@pytest.mark.parametrize("disconnects", [[True], [False, True]])
async def test_cs03_disconnected_probe_never_overwrites_last_result(probe, disconnects):
    _, _, invoke, update = probe
    with pytest.raises(asyncio.CancelledError):
        await validate_model_outlet(ModelOutletValidationRequest(outlet_id=42), "tenant",
            is_disconnected=AsyncMock(side_effect=disconnects))
    assert invoke.await_count == (len(disconnects) - 1)
    update.assert_not_called()


def test_probe_and_agent_terminal_share_exact_bilingual_diagnostics():
    from management.services.model.profiles import _probe_diagnostic
    from nexent.core.model_service.adapters.openai_chat import ModelAdapterError
    from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel
    from nexent.core.model_service.errors import normalize_model_error
    from nexent.core.model_service.http_contracts import ModelTransportError, RawHttpResponse

    for failure in [ModelAdapterError("MODEL_STREAM_AFTER_FINISH"),
                    ModelTransportError("HTTP_STATUS_ERROR", response=RawHttpResponse(500, {}, b"unknown failure"))]:
        error = normalize_model_error(failure, request_id="probe-agent-shared")
        probe = _probe_diagnostic(error)
        terminal = LegacyChatModel._terminal(error)
        assert probe["diagnostic_code"] == error.diagnostic_code
        for lang in ("en", "zh"):
            assert probe["messages"][lang] == terminal.safe_message(lang)
        if error.message_source == "provider":
            assert probe["messages"]["zh"].startswith("模型服务原始错误：(500)")
        else:
            assert "新增正文" in probe["messages"]["zh"]


@pytest.mark.parametrize("ok,status", [(True, "available"), (False, "unavailable")])
def test_ecs02_receipt_matches_effective_request_and_never_reveals_credentials(probe, ok, status):
    import management.services.model.profiles as service

    profile = probe[0]
    receipt = service._issue_check_receipt(profile, "private-key", {"X-Gateway": "private-header"}, ok)
    assert "private-key" not in receipt and "private-header" not in receipt
    assert service._checked_status(receipt, profile, "private-key", {"x-gateway": "private-header"}) == status
    renamed = profile.model_copy(update={"identity": profile.identity.model_copy(update={"display_name": "Renamed"})})
    assert service._checked_status(receipt, renamed, "private-key", {"x-gateway": "private-header"}) == status
    assert service._checked_status(receipt, profile, "new-key", {"x-gateway": "private-header"}) is None
    assert service._checked_status(receipt, profile, "private-key", {"x-gateway": "changed"}) is None
    changed = profile.model_copy(update={"connection": profile.connection.model_copy(update={"timeout_seconds": 1})})
    assert service._checked_status(receipt, changed, "private-key", {"x-gateway": "private-header"}) is None
    other = profile.model_copy(update={"identity": profile.identity.model_copy(update={"tenant_id": "other"})})
    assert service._checked_status(receipt, other, "private-key", {"x-gateway": "private-header"}) is None


def test_ecs04_expired_tampered_and_stale_receipts_are_ignored(probe, monkeypatch):
    import management.services.model.profiles as service

    profile = probe[0]
    receipt = service._issue_check_receipt(profile, "key", {}, True)
    assert service._checked_status(receipt + "bad", profile, "key", {}) is None
    assert service._checked_status("garbage", profile, "key", {}) is None
    stale = profile.model_copy(update={"config_revision": 2})
    assert service._checked_status(receipt, stale, "key", {}) is None
    now = service.time.time()
    monkeypatch.setattr(service.time, "time", lambda: now + 3601)
    assert service._checked_status(receipt, profile, "key", {}) is None


@pytest.mark.asyncio
async def test_ecs01_edit_probe_checks_unsaved_patch_without_writing(probe):
    from contracts.model import ModelOutletPatchRequest
    from management.services.model.profiles import _checked_status, apply_outlet_patch

    profile, _, invoke, update = probe
    patch = ModelOutletPatchRequest(expected_revision=1, connection={"timeout_seconds": 17},
        http_headers={"X-Gateway": "draft-header"})
    result = await validate_model_outlet(ModelOutletValidationRequest(outlet_id=42, patch=patch), "tenant")
    assert result["ok"]
    update.assert_not_called()
    assert invoke.call_args.args[1].connection.timeout_seconds == 17
    proposed = apply_outlet_patch(profile, patch)
    assert _checked_status(result["check_receipt"], proposed, "controlled-key", {"x-gateway": "draft-header"}) == "available"


@pytest.mark.asyncio
async def test_ecs02_create_uses_backend_proof_without_repeating_inference(probe, outlet_database):
    from management.services.model.profiles import create_model_outlet, get_model_profile_catalog

    db, _ = outlet_database
    request = ModelOutletCreateRequest(**draft_request(parameter_values={"enable_thinking": False}).model_dump(), api_key="key")
    request.catalog_revision = get_model_profile_catalog().revision
    checked = await validate_model_outlet(ModelOutletValidationRequest(draft=request), "tenant")
    request.check_receipt = checked["check_receipt"]
    request.display_name = "Renamed after check"
    create_model_outlet(request, "actor", "tenant")
    assert db.create_resolved_model_record.call_args.kwargs["connect_status"] == "available"
    assert probe[2].await_count == 1
    request.api_key = "changed"
    create_model_outlet(request, "actor", "tenant")
    assert db.create_resolved_model_record.call_args.kwargs["connect_status"] == "not_detected"
    assert probe[2].await_count == 1


@pytest.mark.parametrize("patch,key", [({}, "old-key"), ({"api_key": None}, None), ({"api_key": "new-key"}, "new-key")])
def test_ecs01_edit_credential_keep_clear_replace_share_the_same_merge(patch, key):
    from contracts.model import ModelOutletPatchRequest
    from management.services.model.profiles import _patch_credentials

    request = ModelOutletPatchRequest(expected_revision=1, http_headers={"X-Gateway": None}, **patch)
    actual_key, headers = _patch_credentials(request, "old-key", {"x-gateway": "existing-secret"})
    assert actual_key == key and headers == {"x-gateway": "existing-secret"}
    assert "existing-secret" not in repr(request)


@pytest.mark.parametrize("payload", [
    {"draft": {"provider_info": {"base_url": "http://service.invalid"}, "request_model_id": "m"},
     "patch": {"expected_revision": 1}},
    {"outlet_id": 42, "expected_revision": 1, "patch": {"expected_revision": 2}},
])
def test_ecs04_edit_checks_require_one_consistent_saved_revision(payload):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ModelOutletValidationRequest(**payload)
