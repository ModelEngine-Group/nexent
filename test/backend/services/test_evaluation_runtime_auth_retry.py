# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Auth-window retry regressions for evaluation runtime dispatch.

Field evidence (v2.8.4 support incident): the long-lived runtime process
enters transient windows where every internal JWT verification fails with
401 (body code TOKEN_EXPIRED) while fresh processes stay healthy. The
evaluation forwarder retries those windows with a bounded backoff; every
other 401 fails fast so misconfigured secrets surface immediately.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from contracts.errors.exceptions import RuntimeUpstreamError
from management.services.agent import runtime_client


def _auth_window_401():
    return RuntimeUpstreamError(401, b'{"message":"Session expired, please log in again","code":"TOKEN_EXPIRED"}', {})


def _other_401():
    return RuntimeUpstreamError(401, b'{"code":"AGENTOS_UNAUTHORIZED"}', {})


@pytest.mark.asyncio
async def test_auth_window_401_retries_until_success(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(runtime_client.asyncio, "sleep", fake_sleep)
    client = MagicMock()
    client.run_prepared_evaluation = AsyncMock(
        side_effect=[_auth_window_401(), _auth_window_401(), "result"]
    )
    result = await runtime_client._run_prepared_evaluation_with_auth_retry(
        client, "prepared", "u1", "t1"
    )
    assert result == "result"
    assert client.run_prepared_evaluation.await_count == 3
    # Backoff sequence for two retried failures: first two delays.
    assert sleeps == [1.0, 2.0]


@pytest.mark.asyncio
async def test_auth_window_401_exhausts_retries_and_raises_last(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(runtime_client.asyncio, "sleep", fake_sleep)
    client = MagicMock()
    client.run_prepared_evaluation = AsyncMock(side_effect=_auth_window_401())
    with pytest.raises(RuntimeUpstreamError) as excinfo:
        await runtime_client._run_prepared_evaluation_with_auth_retry(
            client, "prepared", "u1", "t1"
        )
    assert excinfo.value.status_code == 401
    # attempts = 1 initial + 6 retries; delays cover the full schedule.
    assert client.run_prepared_evaluation.await_count == 1 + len(runtime_client._EVALUATION_AUTH_RETRY_DELAYS)
    assert sleeps == list(runtime_client._EVALUATION_AUTH_RETRY_DELAYS)


@pytest.mark.asyncio
@pytest.mark.parametrize("exc_factory", [_other_401, lambda: RuntimeUpstreamError(503, b"boom", {})])
async def test_non_window_errors_fail_fast(exc_factory):
    client = MagicMock()
    client.run_prepared_evaluation = AsyncMock(side_effect=exc_factory())
    with pytest.raises(RuntimeUpstreamError):
        await runtime_client._run_prepared_evaluation_with_auth_retry(
            client, "prepared", "u1", "t1"
        )
    assert client.run_prepared_evaluation.await_count == 1


@pytest.mark.asyncio
async def test_success_on_first_attempt_issues_no_sleep(monkeypatch):
    async def fail_sleep(delay):
        raise AssertionError("success on first attempt must not sleep")

    monkeypatch.setattr(runtime_client.asyncio, "sleep", fail_sleep)
    client = MagicMock()
    client.run_prepared_evaluation = AsyncMock(return_value="result")
    result = await runtime_client._run_prepared_evaluation_with_auth_retry(
        client, "prepared", "u1", "t1"
    )
    assert result == "result"
    assert client.run_prepared_evaluation.await_count == 1


def test_is_runtime_auth_window_matches_only_token_expired_401():
    assert runtime_client._is_runtime_auth_window(_auth_window_401()) is True
    assert runtime_client._is_runtime_auth_window(_other_401()) is False
    assert runtime_client._is_runtime_auth_window(RuntimeUpstreamError(503, b"TOKEN_EXPIRED", {})) is False
    assert runtime_client._is_runtime_auth_window(RuntimeError("unrelated")) is False


def test_upstream_body_text_decodes_bytes_and_stringifies_other_content():
    assert runtime_client._upstream_body_text(
        RuntimeUpstreamError(401, b'{"code":"TOKEN_EXPIRED"}', {})
    ) == '{"code":"TOKEN_EXPIRED"}'
    assert runtime_client._upstream_body_text(
        RuntimeUpstreamError(401, '{"code":"TOKEN_EXPIRED"}', {})
    ) == '{"code":"TOKEN_EXPIRED"}'
    assert runtime_client._upstream_body_text(RuntimeUpstreamError(401, None, {})) == ""
    assert runtime_client._upstream_body_text(RuntimeUpstreamError(401, b"", {})) == ""


@pytest.mark.asyncio
async def test_auth_window_with_string_content_still_retries(monkeypatch):
    # Non-bytes upstream content (some transports surface strings) must still
    # be recognized as an auth window and retried.
    sleeps: list[float] = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(runtime_client.asyncio, "sleep", fake_sleep)
    client = MagicMock()
    client.run_prepared_evaluation = AsyncMock(
        side_effect=[
            RuntimeUpstreamError(401, '{"code":"TOKEN_EXPIRED"}', {}),
            "result",
        ]
    )
    result = await runtime_client._run_prepared_evaluation_with_auth_retry(
        client, "prepared", "u1", "t1"
    )
    assert result == "result"
    assert sleeps == [1.0]


@pytest.mark.asyncio
async def test_forward_evaluation_case_uses_retry_wrapper(monkeypatch):
    """The public forwarder routes through the retry wrapper with a live client."""
    prepared_result = MagicMock()
    monkeypatch.setattr(
        "management.services.agent.preparation.evaluation_snapshot.prepare_evaluation_snapshot",
        AsyncMock(return_value=prepared_result),
    )
    captured = {}

    async def fake_retry(client, prepared, user_id, tenant_id):
        captured["client"] = client
        captured["prepared"] = prepared
        return "wrapped"

    monkeypatch.setattr(
        runtime_client, "_run_prepared_evaluation_with_auth_retry", fake_retry
    )
    payload = MagicMock()
    result = await runtime_client.forward_evaluation_case(payload, "u1", "t1")
    assert result == "wrapped"
    assert captured["prepared"] is prepared_result
    assert isinstance(captured["client"], runtime_client.AgentOSClient)


@pytest.mark.asyncio
async def test_forward_evaluation_case_rejects_missing_preparation(monkeypatch):
    monkeypatch.setattr(
        "management.services.agent.preparation.evaluation_snapshot.prepare_evaluation_snapshot",
        AsyncMock(return_value=None),
    )
    from contracts.errors.exceptions import ValidationError

    with pytest.raises(ValidationError):
        await runtime_client.forward_evaluation_case(MagicMock(), "u1", "t1")


# Silence the unused-import linter for asyncio (used by monkeypatched sleep).
_ = asyncio
