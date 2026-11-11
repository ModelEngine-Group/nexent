# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

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
