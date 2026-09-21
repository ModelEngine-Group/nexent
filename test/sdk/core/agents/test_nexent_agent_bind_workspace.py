import json
import logging
from concurrent.futures import CancelledError
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.agents.sandbox import SandboxConfig, SandboxLevel
from nexent.core.agents.sandbox_workspace import SandboxWorkspace
from nexent.core.tools.download_from_s3_tool import DownloadFromS3Tool


@pytest.fixture
def bind_agent(tmp_path):
    workspace = tmp_path / 'user' / 'run'
    (workspace / 'inputs').mkdir(parents=True)
    (workspace / 'outputs').mkdir()
    agent = object.__new__(NexentAgent)
    agent.stop_event = Event()
    agent.workspace_path = str(workspace)
    agent.workspace_run_id = 'run'
    agent.workspace_mapping = SandboxWorkspace(workspace, '/mnt/work/user/run')
    agent.sandbox_config = SandboxConfig(
        level=SandboxLevel.DOCKER, workspace_mode='bind',
        container_workspace_root='/mnt/work', failure_policy='error',
    )
    executor = Mock()
    executor._nexent_backend = 'docker'
    executor._nexent_kernel_recovery_supported = False
    executor._unhealthy = False
    executor.container.id = 'test-container'
    executor.container.exec_run.return_value = SimpleNamespace(exit_code=0, output=b'1000')
    agent._sandbox_executors = [executor]
    agent.agent = SimpleNamespace(python_executor=executor)
    return agent


def test_kernel_bootstrap_uses_container_paths(bind_agent, caplog):
    with caplog.at_level(logging.INFO):
        bind_agent._initialize_sandbox_workspaces()
    code = bind_agent._sandbox_executors[0].call_args.args[0]
    assert '/mnt/work/user/run/outputs' in code
    assert str(bind_agent.workspace_path) not in code
    assert 'Sandbox READY' in caplog.text


def test_cwd_failure_does_not_report_ready(bind_agent, caplog):
    bind_agent._sandbox_executors[0].side_effect = PermissionError('cwd denied')
    with caplog.at_level(logging.INFO), pytest.raises(RuntimeError, match='initialize sandbox workspace'):
        bind_agent._initialize_sandbox_workspaces()
    assert 'Sandbox READY' not in caplog.text
    assert 'phase=workspace' in caplog.text


def test_cancelled_bootstrap_does_not_log_ready_or_initialize_next_kernel(bind_agent, caplog):
    first = bind_agent._sandbox_executors[0]
    second = Mock()
    bind_agent._sandbox_executors.append(second)
    first.side_effect = lambda code: bind_agent.stop_event.set()
    with caplog.at_level(logging.INFO), pytest.raises(CancelledError):
        bind_agent._initialize_sandbox_workspaces()
    first.assert_called_once()
    second.assert_not_called()
    assert 'Sandbox READY' not in caplog.text


def test_bind_push_verifies_access_without_copying(bind_agent):
    bind_agent._push_file_workspace_to_sandbox()
    container = bind_agent._sandbox_executors[0].container
    container.put_archive.assert_not_called()
    commands = [call.args[0] for call in container.exec_run.call_args_list]
    assert any(command[:2] == ['python', '-c'] for command in commands)
    if Path(bind_agent.workspace_path).drive:
        assert not any(command[0] in {'chmod', 'chgrp'} for command in commands)


def test_permission_probe_error_propagates(bind_agent, caplog):
    bind_agent._sandbox_executors[0].container.exec_run.return_value = SimpleNamespace(
        exit_code=1, output=b'permission denied',
    )
    with pytest.raises(RuntimeError):
        bind_agent._push_file_workspace_to_sandbox()
    assert 'phase=workspace_access' in caplog.text


def test_download_returns_kernel_path_but_writes_host_path(tmp_path):
    mapping = SandboxWorkspace(tmp_path, '/mnt/run')
    client = Mock()
    client.get_file_size.return_value = 5

    def download(key, path, bucket):
        Path(path).write_text('hello', encoding='utf-8')
        return True, ''

    client.download_file.side_effect = download
    tool = DownloadFromS3Tool(
        workspace_path=str(tmp_path), minio_client=client,
        validate_url_access=lambda _: None,
    )
    tool.workspace_mapping = mapping
    result = json.loads(tool.forward('s3://bucket/input.txt', 'inputs/input.txt'))
    assert result['local_path'] == '/mnt/run/inputs/input.txt'
    assert (tmp_path / 'inputs' / 'input.txt').read_text(encoding='utf-8') == 'hello'
