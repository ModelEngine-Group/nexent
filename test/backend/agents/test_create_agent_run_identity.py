# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""An injected execution ID reaches both workspace tools and the SDK run object."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from test.backend.agents import test_create_agent_info as legacy
from test.backend.configuration.helpers import system_config_snapshot


@pytest.mark.asyncio
async def test_run_identity_is_not_regenerated_inside_builder(monkeypatch, tmp_path):
    module = sys.modules[legacy.create_agent_run_info.__module__]
    from management.services.agent.preparation import inputs

    monkeypatch.setattr(inputs, 'AGENT_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setattr(module, 'AGENT_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setattr(module, 'get_config_snapshot', Mock(return_value=system_config_snapshot()))
    monkeypatch.setattr(module, 'join_minio_file_description_to_query', AsyncMock(return_value='q'))
    monkeypatch.setattr(module, 'create_model_config_list', AsyncMock(return_value=[]))
    config = SimpleNamespace(sandbox_policy=None, model_name='model')
    compiler = AsyncMock(return_value=config)
    monkeypatch.setattr(module, 'create_agent_config', compiler)
    monkeypatch.setattr(module, 'get_remote_mcp_server_list', AsyncMock(return_value=[]))
    monkeypatch.setattr(module, 'get_tenant_local_mcp_server', Mock(return_value='http://mcp/sse'))
    monkeypatch.setattr(module, 'filter_mcp_servers_and_tools', Mock(return_value=[]))
    monkeypatch.setattr(module, 'apply_root_model_preferences', Mock())
    monkeypatch.setattr(module, '_ensure_agent_reasoning_snapshot', Mock())
    builder = Mock(return_value=SimpleNamespace())
    monkeypatch.setattr(module, 'build_run_info', builder)
    run_id = 'a' * 32
    for _ in range(2):
        await legacy.create_agent_run_info(
            1, [], 'q', [], 'tenant', 'user', override_version_no=1, execution_run_id=run_id,
        )
    paths = [call.kwargs['workspace_path'] for call in builder.call_args_list]
    assert paths[0] == paths[1] == str(tmp_path / 'user' / run_id)
    assert all(call.kwargs['workspace_run_id'] == run_id for call in builder.call_args_list)
    contexts = [call.kwargs['runtime_file_context'] for call in compiler.await_args_list]
    assert all(ctx['run_id'] == run_id and ctx['workspace_path'] == paths[0] for ctx in contexts)
