"""Construction and fallback preserve the run's mapping and resource ownership."""

from concurrent.futures import CancelledError
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.core.agents import nexent_agent as agent_module
from nexent.core.agents import sandbox
from nexent.core.agents.agent_model import AgentConfig, ToolConfig
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.utils.observer import MessageObserver


@pytest.fixture
def factory(tmp_path):
    config = sandbox.SandboxConfig(
        level=sandbox.SandboxLevel.DOCKER, workspace_mode='bind',
        container_workspace_root='/mnt/work', failure_policy='error',
        extra_kwargs={'workspace_root': str(tmp_path)},
    )
    return NexentAgent(
        observer=Mock(spec=MessageObserver), model_config_list=[], stop_event=Event(),
        sandbox_config=config, workspace_path=str(tmp_path / 'run'), workspace_run_id='run',
    )


def test_constructor_creates_run_scoped_mapping(factory, tmp_path):
    assert factory.workspace_mapping.host_root == tmp_path / 'run'
    assert str(factory.workspace_mapping.container_root) == '/mnt/work/run'


def test_explicit_local_bind_config_keeps_mapping_disabled(tmp_path):
    config = sandbox.SandboxConfig(workspace_mode='bind', container_workspace_root='/mnt/work')
    agent = NexentAgent(Mock(spec=MessageObserver), [], Event(), sandbox_config=config, workspace_path=str(tmp_path))
    assert agent.workspace_mapping is None


@pytest.mark.parametrize('class_name', [
    'CreateFileTool', 'ReadFileTool', 'DeleteFileTool', 'DownloadFromS3Tool', 'UploadToS3Tool', 'OtherTool',
])
def test_tool_binding_preserves_each_tools_directory(factory, mocker, class_name):
    tool = SimpleNamespace(init_path='original')
    mocker.patch.object(factory, 'create_local_tool', return_value=tool)
    config = ToolConfig(name=class_name, class_name=class_name, source='local', params={})
    assert factory.create_tool(config) is tool
    if class_name == 'OtherTool':
        assert not hasattr(tool, 'workspace_mapping')
    else:
        assert tool.workspace_mapping is factory.workspace_mapping
    expected = str(factory.workspace_mapping.host_root / 'outputs') if class_name in {
        'CreateFileTool', 'ReadFileTool', 'DeleteFileTool',
    } else 'original'
    assert tool.init_path == expected


@pytest.fixture
def construction(factory, mocker):
    mocker.patch.object(factory, 'create_model', return_value=Mock())
    executor = Mock(_nexent_backend='docker', _nexent_session_container_group=None)
    mocker.patch.object(sandbox, 'build_python_executor', return_value=executor)
    core = mocker.patch.object(agent_module, 'CoreAgent', return_value=SimpleNamespace(enable_planning=False))
    cleanup = mocker.patch.object(factory, '_cleanup_sandbox')
    config = AgentConfig(name='agent', description='test', model_name='model', tools=[], managed_agents=[])
    return SimpleNamespace(factory=factory, executor=executor, core=core, cleanup=cleanup, config=config)


@pytest.mark.parametrize('error', [RuntimeError('warm failed'), CancelledError('cancelled')])
def test_strict_warmup_failure_releases_acquired_executor(construction, error):
    c = construction
    c.executor.side_effect = error
    expected = CancelledError if isinstance(error, CancelledError) else ValueError
    with pytest.raises(expected):
        c.factory.create_single_agent(c.config)
    c.cleanup.assert_called_once()
    c.core.assert_not_called()


def test_strict_mode_rejects_unexpected_local_executor(construction):
    c = construction
    c.executor._nexent_backend = 'local'
    with pytest.raises(ValueError, match='phase=warmup'):
        c.factory.create_single_agent(c.config)
    c.cleanup.assert_called_once()


def test_cleanup_failure_does_not_hide_construction_failure(construction, caplog):
    c = construction
    c.executor.side_effect = RuntimeError('warm failed')
    c.cleanup.side_effect = RuntimeError('cleanup failed')
    with pytest.raises(ValueError, match='phase=warmup'):
        c.factory.create_single_agent(c.config)
    assert 'Failed to release sandbox resources' in caplog.text


def test_allowed_local_fallback_clears_mappings_and_warns(construction, mocker):
    c = construction
    c.factory.sandbox_config.failure_policy = 'local'
    c.executor._nexent_backend = 'local'
    tool = Mock(name='file-tool')
    tool.workspace_mapping = c.factory.workspace_mapping
    plain_tool = Mock(name='plain-tool', workspace_mapping=None)
    c.config.tools = [ToolConfig(name='read', class_name='ReadFileTool', source='local', params={})] * 2
    mocker.patch.object(c.factory, 'create_tool', side_effect=[tool, plain_tool])
    mocker.patch.object(agent_module, '_wrap_tool_with_monitoring', side_effect=lambda tool, _: tool)
    result = c.factory.create_single_agent(c.config)
    assert result is c.core.return_value
    assert c.factory.workspace_mapping is None
    assert tool.workspace_mapping is None
    c.factory.observer.add_message.assert_called_once()
    c.cleanup.assert_not_called()
