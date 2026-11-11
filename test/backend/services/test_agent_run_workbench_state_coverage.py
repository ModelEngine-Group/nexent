# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from test.backend.services import test_agent_run_workbench_coverage as base
from management.services.agent import conversation_preparation
from contracts.errors.exceptions import RuntimeCapacityExceededError


agent_run = base.agent_subscription
_request = base._request


def _configure_early_workbench_run(monkeypatch, canonical, conversation):
    plan = SimpleNamespace(root=SimpleNamespace(identity=SimpleNamespace(agent_id=99)))
    workbench_module = ModuleType("management.services.agent.workbench")
    workbench_module.assert_workbench_version = MagicMock()
    workbench_module.resolve_workbench_config = MagicMock(return_value=(canonical, plan))
    monkeypatch.setitem(sys.modules, "management.services.agent.workbench", workbench_module)
    monkeypatch.setattr(conversation_preparation, "ENABLE_AGENT_WORKBENCH", True)
    monkeypatch.setattr(
        agent_run,
        "_resolve_user_tenant_language",
        lambda **_kwargs: ("user-a", "tenant-a", "en"),
    )
    monkeypatch.setattr(conversation_preparation, "prepend_current_time", lambda query, _timezone, *, language: query)
    monkeypatch.setattr(conversation_preparation, "get_conversation_service", lambda **_kwargs: conversation)
    monkeypatch.setattr(
        conversation_preparation,
        "apply_workbench_runtime_plan",
        lambda request, *_args: request.__dict__.update({"agent_id": 99, "version_no": 5}),
    )
    monkeypatch.setattr(conversation_preparation, "update_conversation_chat_mode_service", MagicMock())
    return SimpleNamespace(admit=AsyncMock(side_effect=RuntimeCapacityExceededError()))



@pytest.mark.asyncio
async def test_existing_workbench_commits_config_and_metadata_atomically(monkeypatch):
    from fastapi import Request
    from contracts.agent import WorkbenchSessionConfig
    canonical = WorkbenchSessionConfig.model_validate({'mode': 'single_agent_chat', 'agent_mounts': [{'agent_id': 7}]})
    conversation = {'workbench_config': canonical.model_dump(mode='json'), 'workbench_config_version': 2, 'runtime_metadata': {'old': True}, 'runtime_metadata_version': 4, 'knowledge_scope': None}
    request = _request(entrypoint='workbench', workbench=canonical, expected_workbench_config_version=2, metadata={'ticket': 'NEX-1'}, expected_metadata_version=4)
    host = _configure_early_workbench_run(monkeypatch, canonical, conversation)
    joint = MagicMock(return_value={'workbench_config_version': 3, 'runtime_metadata': {'ticket': 'NEX-1'}, 'runtime_metadata_version': 5})
    monkeypatch.setattr(conversation_preparation, 'update_conversation_workbench_and_metadata_service', joint)
    with pytest.raises(RuntimeCapacityExceededError):
        await agent_run.run_agent_stream(request, Request(scope={'type': 'http', 'headers': []}), user_id='test_user', tenant_id='test_tenant', thread_manager=object(), execution_host=host)
    joint.assert_called_once()
    host.admit.assert_awaited_once()
    assert request.__dict__['_runtime_metadata_snapshot'] == {'ticket': 'NEX-1'}
    assert request.__dict__['_runtime_metadata_version'] == 5
    conflict_request = _request(entrypoint='workbench', workbench=canonical, expected_workbench_config_version=2, metadata={'ticket': 'NEX-2'}, expected_metadata_version=4)
    joint.side_effect = conversation_preparation.RuntimeMetadataVersionConflict(5)
    with pytest.raises(conversation_preparation.AppException) as caught:
        await agent_run.run_agent_stream(conflict_request, Request(scope={'type': 'http', 'headers': []}), user_id='test_user', tenant_id='test_tenant', thread_manager=object(), execution_host=host)
    assert caught.value.error_code == conversation_preparation.ErrorCode.CHAT_METADATA_VERSION_CONFLICT


@pytest.mark.asyncio
async def test_new_workbench_conversation_persists_canonical_config(monkeypatch):
    from fastapi import Request
    from contracts.agent import WorkbenchSessionConfig
    canonical = WorkbenchSessionConfig.model_validate({'mode': 'single_agent_chat', 'agent_mounts': [{'agent_id': 7}]})
    request = _request(conversation_id=None, entrypoint='workbench', workbench=canonical)
    host = _configure_early_workbench_run(monkeypatch, canonical, None)
    create = MagicMock(return_value={'conversation_id': 321, 'workbench_config_version': 1, 'runtime_metadata': {}, 'runtime_metadata_version': 0})
    monkeypatch.setattr(conversation_preparation, 'create_new_conversation', create)
    with pytest.raises(RuntimeCapacityExceededError):
        await agent_run.run_agent_stream(request, Request(scope={'type': 'http', 'headers': []}), user_id='test_user', tenant_id='test_tenant', thread_manager=object(), execution_host=host)
    assert create.call_args.kwargs['workbench_config'] == canonical.model_dump(mode='json')
    assert request.conversation_id == 321
    assert request.__dict__['_workbench_config_version'] == 1


@pytest.mark.asyncio
async def test_workbench_run_requires_configuration_after_request_normalization(monkeypatch):
    from fastapi import Request
    from contracts.agent import WorkbenchSessionConfig
    canonical = WorkbenchSessionConfig.model_validate({'mode': 'single_agent_chat', 'agent_mounts': [{'agent_id': 7}]})
    request = _request(conversation_id=None, entrypoint='workbench', workbench=canonical)
    request.__dict__['workbench'] = None
    host = _configure_early_workbench_run(monkeypatch, canonical, None)
    with pytest.raises(conversation_preparation.ValidationError, match='configuration is required'):
        await agent_run.run_agent_stream(request, Request(scope={'type': 'http', 'headers': []}), user_id='test_user', tenant_id='test_tenant', thread_manager=object(), execution_host=host)
