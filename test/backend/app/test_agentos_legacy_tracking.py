# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from infrastructure.rdb.agent_execution import RunIdentity
from runtime.agentos import legacy_tracking


@pytest.mark.asyncio
async def test_legacy_tracking_registers_the_original_scoped_identity(mocker):
    scope = RunIdentity("tenant", "owner", 42, "a" * 32)
    persist = mocker.patch.object(legacy_tracking, "run_blocking")
    track = mocker.patch.object(legacy_tracking, "track_execution")

    assert await legacy_tracking.begin_legacy_tracking(42, scope.run_id, "owner", "tenant") == scope
    persist.assert_awaited_once_with(
        "agentos-execution-start", legacy_tracking.begin_execution, scope, lane="control-io", owner="runtime",
    )
    track.assert_called_once_with(scope)


@pytest.mark.asyncio
@pytest.mark.parametrize("ledger_error", [False, True])
async def test_setup_failure_releases_live_registration_even_if_ledger_write_fails(mocker, ledger_error):
    scope = RunIdentity("tenant", "owner", 42, "a" * 32)
    persist = mocker.patch.object(legacy_tracking, "run_blocking")
    untrack = mocker.patch.object(legacy_tracking, "untrack_execution")
    if ledger_error:
        persist.side_effect = RuntimeError("ledger unavailable")
        with pytest.raises(RuntimeError, match="ledger unavailable"):
            await legacy_tracking.fail_legacy_setup(scope)
    else:
        await legacy_tracking.fail_legacy_setup(scope)

    persist.assert_awaited_once_with(
        "agentos-execution-setup-failed", legacy_tracking.finish_execution, scope, "failed",
        lane="control-io", owner="runtime",
    )
    untrack.assert_called_once_with(scope)


@pytest.mark.asyncio
@pytest.mark.parametrize("journal_id", [None, "a" * 32])
async def test_channel_binds_claim_to_the_runtime_journal_availability(mocker, journal_id):
    identity = RunIdentity("tenant", "owner", 42, "a" * 32)
    channel = SimpleNamespace(start_journal=AsyncMock(return_value=journal_id))
    mocker.patch.object(legacy_tracking, "runtime_state_service", SimpleNamespace(enabled=True))
    persist = mocker.patch.object(legacy_tracking, "run_blocking", return_value=True)

    result = await legacy_tracking.bind_legacy_channel(
        channel, identity.run_id, "owner", "tenant", conversation_id=42, identity=identity, admission_scope="claim",
    )

    assert result == journal_id and channel.execution_identity == identity
    channel.start_journal.assert_awaited_once_with("tenant", identity.run_id)
    persist.assert_awaited_once_with(
        "agentos-bind-conversation", legacy_tracking.set_conversation_admission, "claim",
        identity.run_id, "owner", "tenant", conversation_id=42, journal_available=journal_id is not None,
        lane="control-io", owner="runtime",
    )
