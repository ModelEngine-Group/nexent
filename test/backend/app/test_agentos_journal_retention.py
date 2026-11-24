# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify journal retention writes and scoped projection acknowledgment."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from redis.exceptions import RedisError

from contracts.agentos import AgentRunReference
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.redis import agent_events
from runtime.agentos import resume


@pytest.mark.parametrize("retain_for_projection", [False, True])
def test_journal_limits_depend_on_projection_retention(mocker, retain_for_projection):
    client = MagicMock()
    pipe = client.pipeline.return_value.__enter__.return_value
    mocker.patch.object(agent_events, "runtime_state_service", SimpleNamespace(client=client))
    journal = agent_events.RunJournal("tenant", "owner", 12, "a" * 32, retain_for_projection)

    journal.start()
    journal.append(10_001, "chunk")
    journal.finish(10_002, "completed")

    writes = [invocation.kwargs["maxlen"] for invocation in pipe.xadd.call_args_list]
    assert writes == [None if retain_for_projection else agent_events.RUNTIME_STREAM_MAX_LEN] * 3
    start = pipe.xadd.call_args_list[0].args[1]
    assert start.get("retention") == ("projection" if retain_for_projection else None)
    terminal_ttl = (
        agent_events.RUNTIME_STREAM_TTL_SECONDS if retain_for_projection else agent_events.RUNTIME_COMPLETED_TTL_SECONDS
    )
    pipe.expire.assert_called_with(journal.key, terminal_ttl)


@pytest.mark.asyncio
@pytest.mark.parametrize("store_error", [False, True])
async def test_acknowledgment_uses_the_authenticated_run_scope(mocker, store_error):
    reference = AgentRunReference(conversation_id=12, run_id="a" * 32)
    actor = ServicePrincipal("owner", "tenant")
    journal = mocker.Mock()
    if store_error:
        journal.acknowledge_projection.side_effect = RedisError("unavailable")
    owned = mocker.patch.object(resume, "_owned_journal", return_value=journal)

    async def run_inline(_task, callback, *args):
        return callback(*args)

    mocker.patch.object(resume, "_control_io", side_effect=run_inline)
    if store_error:
        with pytest.raises(HTTPException) as error:
            await resume.acknowledge_projection(reference, actor)
        assert error.value.status_code == 503
    else:
        assert await resume.acknowledge_projection(reference, actor) == {}
    owned.assert_awaited_once_with(reference, actor)
    journal.acknowledge_projection.assert_called_once_with()
