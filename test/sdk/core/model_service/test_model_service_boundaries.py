# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Invalid call policies must fail before credentials, transport or retry waits."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.core.concurrency.cancellation import RunCancellationScope, RunTerminated
from nexent.core.model_service.http_contracts import ModelTransportError
from nexent.core.model_service.service import ModelRequestRetryPolicy, ModelService, ModelServiceError
from test.sdk.core.model_service.test_model_service import Sender, setup


@pytest.mark.parametrize("attempts", [0, -1, True, 1.5])
def test_retry_policy_requires_a_positive_integer(attempts):
    with pytest.raises(ValueError, match="positive integer"):
        ModelRequestRetryPolicy(max_attempts=attempts)
    sender = Mock()
    with pytest.raises(ValueError, match="positive integer"):
        ModelService(sender, retry_policy=SimpleNamespace(max_attempts=attempts))
    sender.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["invoke", "ainvoke", "stream", "astream"])
async def test_wrong_request_mode_does_not_resolve_credentials(setup, mode):
    profile, request, _, _ = setup
    sender = Mock()
    model = ModelService(sender)
    request = request.model_copy(update={"stream": mode.endswith("invoke")})
    with pytest.raises(ValueError, match="requires"):
        if mode == "invoke":
            model.invoke(request, profile)
        elif mode == "ainvoke":
            await model.ainvoke(request, profile)
        elif mode == "stream":
            with model.stream(request, profile):
                pytest.fail("Invalid mode must not enter the stream")
        else:
            async with model.astream(request, profile):
                pytest.fail("Invalid mode must not enter the stream")
    sender.assert_not_called()


@pytest.mark.parametrize("deadline", [True, float("nan"), float("inf"), "soon"])
def test_invalid_deadline_cannot_start_a_model_request(setup, deadline):
    profile, request, _, _ = setup
    sender = Mock()
    with pytest.raises(ValueError, match="finite monotonic"):
        ModelService(sender).invoke(request, profile, deadline=deadline)
    sender.assert_not_called()


def test_cancelled_call_never_freezes_credentials(setup):
    profile, request, _, _ = setup
    scope = RunCancellationScope()
    scope.cancel()
    sender = Mock()
    with pytest.raises(RunTerminated):
        ModelService(sender).invoke(request, profile, scope=scope)
    sender.assert_not_called()


@pytest.mark.parametrize("delay", [-1, float("inf"), float("nan"), "later"])
def test_invalid_retry_delay_cannot_wait_or_send_again(setup, delay):
    profile, request, _, _ = setup
    sender = Sender([ModelTransportError("HTTP_NETWORK_ERROR")])
    policy = SimpleNamespace(max_attempts=2, calculate_backoff=lambda _: delay)
    with pytest.raises(ValueError, match="finite and nonnegative"):
        ModelService(lambda _: sender, retry_policy=policy).invoke(request, profile)
    assert len(sender.calls) == 1


def test_sender_initialization_failure_uses_the_normalized_error_contract(setup):
    profile, request, _, _ = setup
    sender = Mock(side_effect=RuntimeError("cannot initialize sender"))
    with pytest.raises(ModelServiceError) as failure:
        ModelService(sender).invoke(request, profile)
    assert failure.value.error.request_id == request.request_id
    sender.assert_called_once()


def test_unrecognized_empty_response_policy_does_not_acquire_transport(setup):
    profile, request, _, _ = setup
    sender = Mock()
    with pytest.raises(ValueError, match="empty response policy"):
        with ModelService(sender).stream(request.model_copy(update={"stream": True}), profile,
                                         empty_response_policy="guess"):
            pytest.fail("Unknown policy cannot start a stream")
    sender.assert_not_called()
