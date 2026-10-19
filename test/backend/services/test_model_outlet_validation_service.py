# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Connection probes capture configuration once and preserve revision/cancellation boundaries."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from consts.exceptions import ModelOutletConflictError
from consts.model import ModelOutletCreateRequest, ModelOutletValidationRequest
from nexent.core.model_service.contracts import AssistantMessage, ModelError, ModelEvent
from nexent.core.model_service.service import ModelServiceError
from services.model_profile_service import build_outlet_draft, validate_model_outlet

from test.backend.services.test_model_profile_service import draft_request, outlet_database  # noqa: F401


@pytest.fixture
def probe(monkeypatch, outlet_database):
    import nexent.core.concurrency as concurrency
    import nexent.core.model_service.service as model_service
    import services.model_profile_service as service

    profile, _ = build_outlet_draft(draft_request(parameter_values={"enable_thinking": False}), "tenant")
    data = profile.model_dump()
    data["outlet_id"] = data["connection"]["credential_ref"]["model_id"] = 42
    profile = profile.__class__.model_validate(data)
    loader = Mock(return_value=(profile, "controlled-key"))
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
