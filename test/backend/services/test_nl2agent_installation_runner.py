"""Focused tests for the shared durable NL2AGENT installation runner."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from consts.exceptions import AgentRunException
from database.nl2agent_installation_db import (
    InstallationLeaseActiveError,
    InstallationRequestConflictError,
)
from database.nl2agent_session_db import Nl2AgentSessionIdentity
from services import nl2agent_runtime_service
from services.nl2agent_installation_runner import (
    DurableInstallationRunner,
    InstallationRunRequest,
    InstallationRunnerRepository,
)


def _identity() -> Nl2AgentSessionIdentity:
    return Nl2AgentSessionIdentity(
        tenant_id="tenant-a",
        user_id="user-a",
        runner_agent_id=7,
        draft_agent_id=11,
        conversation_id=22,
    )


def _request(**overrides) -> InstallationRunRequest:
    values = {
        "installation_key": "stable-key",
        "request_fingerprint": "fingerprint-a",
        "resource_type": "mcp",
    }
    values.update(overrides)
    return InstallationRunRequest(**values)


def _runner(
    *,
    claim=None,
    renew=None,
    transition=None,
    release=None,
    heartbeat_seconds=60,
):
    repository = InstallationRunnerRepository(
        claim=claim or MagicMock(return_value={"status": "running", "checkpoint": {}}),
        renew=renew or MagicMock(return_value=True),
        transition=transition or MagicMock(return_value=True),
        release=release or MagicMock(return_value=True),
    )
    return (
        DurableInstallationRunner(
            identity=_identity(),
            repository=repository,
            lease_seconds=30,
            heartbeat_seconds=heartbeat_seconds,
        ),
        repository,
    )


@pytest.mark.asyncio
async def test_completed_operation_replays_without_provider_io():
    runner, repository = _runner(
        claim=MagicMock(
            return_value={
                "status": "completed",
                "result": {"mcp_id": 5},
                "checkpoint": {"provider_persisted": True},
            }
        )
    )
    execute = AsyncMock()

    result = await runner.run(_request(), execute)

    assert result == {"mcp_id": 5}
    execute.assert_not_awaited()
    repository.transition.assert_not_called()


@pytest.mark.asyncio
async def test_expired_operation_resumes_from_checkpoint():
    transition = MagicMock(return_value=True)
    runner, _ = _runner(
        claim=MagicMock(
            return_value={
                "status": "running",
                "attempt": 2,
                "checkpoint": {"provider_persisted": True, "mcp_id": 5},
            }
        ),
        transition=transition,
    )

    async def execute(context, checkpoint):
        assert checkpoint == {"provider_persisted": True, "mcp_id": 5}
        await context.save_checkpoint({"discovery_completed": True})
        return {"mcp_id": 5, "status": "connected"}

    result = await runner.run(_request(), execute)

    assert result == {"mcp_id": 5, "status": "connected"}
    assert [call.kwargs["status"] for call in transition.call_args_list] == [
        "running",
        "completed",
    ]


@pytest.mark.asyncio
async def test_heartbeat_failure_cancels_provider_and_persists_redacted_failure():
    runner, repository = _runner(
        renew=MagicMock(return_value=False),
        heartbeat_seconds=0,
    )
    cancelled = asyncio.Event()

    async def execute(_context, _checkpoint):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with pytest.raises(AgentRunException, match="ownership was lost"):
        await runner.run(_request(), execute)

    assert cancelled.is_set()
    failure = repository.transition.call_args
    assert failure.kwargs["status"] == "failed"
    assert failure.kwargs["error"] == {
        "code": "installation_failed",
        "message": "Installation failed; retry is allowed.",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "message"),
    [
        (
            InstallationLeaseActiveError("active"),
            "already in progress",
        ),
        (
            InstallationRequestConflictError("different"),
            "different request",
        ),
    ],
)
async def test_claim_conflicts_fail_before_provider_io(error, message):
    runner, _ = _runner(claim=MagicMock(side_effect=error))
    execute = AsyncMock()

    with pytest.raises(AgentRunException, match=message):
        await runner.run(_request(), execute)

    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_result_and_checkpoint_persistence_drop_secret_fields():
    transition = MagicMock(return_value=True)
    runner, _ = _runner(transition=transition)

    async def execute(context, _checkpoint):
        await context.save_checkpoint(
            {
                "provider_persisted": True,
                "authorization_token": "checkpoint-secret",
            }
        )
        return {
            "mcp_id": 5,
            "token": "result-secret",
            "nested": {"password": "nested-secret", "status": "connected"},
        }

    result = await runner.run(_request(), execute)

    assert result == {"mcp_id": 5, "nested": {"status": "connected"}}
    persisted = transition.call_args_list[-1].kwargs
    assert "secret" not in str(persisted)
    assert persisted["checkpoint"] == {"provider_persisted": True}


@pytest.mark.asyncio
async def test_provider_io_starts_only_after_claim_returns():
    events = []

    def claim(**_kwargs):
        events.extend(["claim_started", "claim_committed"])
        return {"status": "running", "checkpoint": {}}

    runner, _ = _runner(claim=claim)

    async def execute(_context, _checkpoint):
        events.append("provider_io")
        return {"ok": True}

    await runner.run(_request(), execute)

    assert events == ["claim_started", "claim_committed", "provider_io"]


def test_mcp_and_skill_composition_use_the_same_runner(monkeypatch):
    runner = MagicMock(spec=DurableInstallationRunner)
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "require_active_session",
        MagicMock(return_value={"runner_agent_id": 7, "conversation_id": 22}),
    )
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "build_default_installation_runner",
        MagicMock(return_value=runner),
    )

    mcp_dependencies = nl2agent_runtime_service._mcp_installation_dependencies(
        "user-a", "tenant-a", 11
    )
    skill_dependencies = nl2agent_runtime_service._skill_installation_dependencies(
        "user-a", "tenant-a", 11
    )

    assert mcp_dependencies.runner is runner
    assert skill_dependencies.runner is runner
