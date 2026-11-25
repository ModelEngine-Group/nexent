# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Verify AgentOS keeps the admitted run ID across ownership and durable journal bindings."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from runtime.agentos import prepared_run
from test.backend.app.test_agentos_prepared_run import ACTOR, RUN_ID, payload, runtime  # noqa: F401


@pytest.mark.asyncio
async def test_prepared_run_uses_one_id_for_ownership_journal_and_worker(monkeypatch, payload, runtime):
    reserve = AsyncMock()
    release = AsyncMock()
    monkeypatch.setattr(prepared_run, "reserve_agentos_sandbox", reserve)
    monkeypatch.setattr(prepared_run, "release_agentos_sandbox", release)

    async def agent(_info, **_kwargs):
        yield '{"type":"final_answer","content":"done"}'

    monkeypatch.setattr(prepared_run, "agent_run", agent)
    receipt = await prepared_run.start_prepared_run(payload, ACTOR)
    await asyncio.wait_for(asyncio.gather(*runtime.tasks), timeout=2)
    assert receipt.run_id == RUN_ID
    assert reserve.await_args.args == (ACTOR.tenant_id, ACTOR.user_id, payload.conversation_id, RUN_ID)
    assert runtime.begin.call_args.args[0].run_id == RUN_ID
    runtime.prepare.assert_awaited_once_with(payload, ACTOR, prepared_run.prepare_run_snapshot)
    assert runtime.finish.call_args.args[0].run_id == RUN_ID
    release.assert_awaited_once()
    assert release.await_args.args[0] is reserve.return_value
