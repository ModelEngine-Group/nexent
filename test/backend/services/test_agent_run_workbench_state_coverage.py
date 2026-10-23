import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

from test.backend.services import test_agent_run_workbench_coverage as base


agent_run = base.agent_run
_request = base._request


def _configure_early_workbench_run(monkeypatch, canonical, conversation):
    plan = SimpleNamespace(root=SimpleNamespace(identity=SimpleNamespace(agent_id=99)))
    workbench_module = ModuleType("services.workbench_service")
    workbench_module.assert_workbench_version = MagicMock()
    workbench_module.resolve_workbench_config = MagicMock(return_value=(canonical, plan))
    monkeypatch.setitem(sys.modules, "services.workbench_service", workbench_module)
    monkeypatch.setattr(agent_run, "ENABLE_AGENT_WORKBENCH", True)
    monkeypatch.setattr(
        agent_run,
        "_resolve_user_tenant_language",
        lambda **_kwargs: ("user-a", "tenant-a", "en"),
    )
    monkeypatch.setattr(agent_run, "prepend_current_time", lambda query, _timezone: query)
    monkeypatch.setattr(agent_run, "get_conversation_service", lambda **_kwargs: conversation)
    monkeypatch.setattr(
        agent_run,
        "apply_workbench_runtime_plan",
        lambda request, *_args: request.__dict__.update({"agent_id": 99, "version_no": 5}),
    )
    monkeypatch.setattr(agent_run, "update_conversation_chat_mode_service", MagicMock())
    monkeypatch.setattr(
        agent_run.agent_run_manager,
        "reserve_agent_capacity",
        MagicMock(side_effect=agent_run.AgentRunConcurrencyExceededError()),
    )


@pytest.mark.asyncio
async def test_existing_workbench_commits_config_and_metadata_atomically(monkeypatch):
    from fastapi import Request
    from consts.model import WorkbenchSessionConfig

    canonical = WorkbenchSessionConfig.model_validate(
        {"mode": "single_agent_chat", "agent_mounts": [{"agent_id": 7}]}
    )
    conversation = {
        "workbench_config": canonical.model_dump(mode="json"),
        "workbench_config_version": 2,
        "runtime_metadata": {"old": True},
        "runtime_metadata_version": 4,
        "knowledge_scope": None,
    }
    request = _request(
        entrypoint="workbench",
        workbench=canonical,
        expected_workbench_config_version=2,
        metadata={"ticket": "NEX-1"},
        expected_metadata_version=4,
    )
    _configure_early_workbench_run(monkeypatch, canonical, conversation)
    joint = MagicMock(
        return_value={
            "workbench_config_version": 3,
            "runtime_metadata": {"ticket": "NEX-1"},
            "runtime_metadata_version": 5,
        }
    )
    monkeypatch.setattr(
        agent_run, "update_conversation_workbench_and_metadata_service", joint
    )

    with pytest.raises(agent_run.RuntimeCapacityExceededError):
        await agent_run.run_agent_stream(
            request, Request(scope={"type": "http", "headers": []}), "Bearer token"
        )

    joint.assert_called_once()
    assert request.__dict__["_runtime_metadata_snapshot"] == {"ticket": "NEX-1"}
    assert request.__dict__["_runtime_metadata_version"] == 5

    conflict_request = _request(
        entrypoint="workbench",
        workbench=canonical,
        expected_workbench_config_version=2,
        metadata={"ticket": "NEX-2"},
        expected_metadata_version=4,
    )
    joint.side_effect = agent_run.RuntimeMetadataVersionConflict(5)
    with pytest.raises(agent_run.AppException) as caught:
        await agent_run.run_agent_stream(
            conflict_request,
            Request(scope={"type": "http", "headers": []}),
            "Bearer token",
        )
    assert caught.value.error_code == agent_run.ErrorCode.CHAT_METADATA_VERSION_CONFLICT


@pytest.mark.asyncio
async def test_new_workbench_conversation_persists_canonical_config(monkeypatch):
    from fastapi import Request
    from consts.model import WorkbenchSessionConfig

    canonical = WorkbenchSessionConfig.model_validate(
        {"mode": "single_agent_chat", "agent_mounts": [{"agent_id": 7}]}
    )
    request = _request(conversation_id=None, entrypoint="workbench", workbench=canonical)
    _configure_early_workbench_run(monkeypatch, canonical, None)
    create = MagicMock(
        return_value={
            "conversation_id": 321,
            "workbench_config_version": 1,
            "runtime_metadata": {},
            "runtime_metadata_version": 0,
        }
    )
    monkeypatch.setattr(agent_run, "create_new_conversation", create)

    with pytest.raises(agent_run.RuntimeCapacityExceededError):
        await agent_run.run_agent_stream(
            request, Request(scope={"type": "http", "headers": []}), "Bearer token"
        )

    assert create.call_args.kwargs["workbench_config"] == canonical.model_dump(mode="json")
    assert request.conversation_id == 321
    assert request.__dict__["_workbench_config_version"] == 1


@pytest.mark.asyncio
async def test_workbench_run_requires_configuration_after_request_normalization(
    monkeypatch,
):
    from fastapi import Request
    from consts.model import WorkbenchSessionConfig

    canonical = WorkbenchSessionConfig.model_validate(
        {"mode": "single_agent_chat", "agent_mounts": [{"agent_id": 7}]}
    )
    request = _request(conversation_id=None, entrypoint="workbench", workbench=canonical)
    request.__dict__["workbench"] = None
    _configure_early_workbench_run(monkeypatch, canonical, None)

    with pytest.raises(agent_run.ValidationError, match="configuration is required"):
        await agent_run.run_agent_stream(
            request, Request(scope={"type": "http", "headers": []}), "Bearer token"
        )
