# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import json
import logging
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.core.agents.sandbox import execution as sandbox
from nexent.core.agents.resources.workspace import SandboxWorkspace, WorkspaceResources, probe_workspace
from nexent.core.tools.create_file_tool import CreateFileTool
from nexent.core.tools.read_file_tool import ReadFileTool
from nexent.core.tools.upload_to_s3_tool import UploadToS3Tool


def test_mapping_roundtrip_and_run_boundary(tmp_path):
    mapping = SandboxWorkspace(tmp_path, '/mnt/work')
    run = mapping.for_run(tmp_path / 'user' / 'run')
    path = tmp_path / 'user' / 'run' / 'outputs' / '中文 folder' / 'result.txt'
    assert str(run.to_container(path)) == '/mnt/work/user/run/outputs/中文 folder/result.txt'
    assert run.to_host(str(run.to_container(path))) == path
    with pytest.raises(ValueError):
        run.to_host('/mnt/work/user/other/file.txt')
    with pytest.raises(ValueError):
        run.to_container(tmp_path / 'user' / 'run-other' / 'file.txt')


@pytest.mark.parametrize('value', ['/mnt/work/../secret', r'/mnt/work/a\b', '/mnt/work/a:b', 'D:/work'])
def test_reject_unsafe_container_paths(tmp_path, value):
    mapping = SandboxWorkspace(tmp_path, '/mnt/work')
    with pytest.raises(ValueError):
        mapping.to_host(value)


def test_symlink_escape(tmp_path):
    root = tmp_path / 'run'
    root.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    try:
        (root / 'link').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Host does not permit symlink creation')
    mapping = SandboxWorkspace(root, '/mnt/run')
    with pytest.raises(ValueError):
        mapping.to_host('/mnt/run/link/secret')


def test_permission_probe_failure_is_not_ignored(mocker):
    container = Mock()
    container.exec_run.return_value = SimpleNamespace(exit_code=1, output=b'Permission denied')
    with pytest.raises(RuntimeError, match='workspace access failed'):
        probe_workspace(container, Path('/mnt/run'))


@pytest.mark.parametrize('scope', list(sandbox.SandboxScope))
def test_bind_mount_has_distinct_source_and_target(tmp_path, mocker, scope):
    manager = object.__new__(sandbox.SandboxPoolManager)
    config = sandbox.SandboxConfig(
        level=sandbox.SandboxLevel.DOCKER, scope=scope, workspace_mode='bind',
        container_workspace_root='/mnt/work', failure_policy='error',
        extra_kwargs={'workspace_root': str(tmp_path)},
    )
    mocker.patch('smolagents.remote_executors.DockerExecutor', Mock())
    mocker.patch.object(sandbox, '_wrap_executor', side_effect=lambda executor, *_: executor)
    mocker.patch.object(sandbox, '_ensure_sandbox_control_network')
    mocker.patch('docker.from_env')
    method = '_build_system_docker_executor' if scope == sandbox.SandboxScope.SYSTEM else '_build_session_docker_executor'
    build = mocker.patch.object(manager, method, return_value=SimpleNamespace())
    manager._build_docker_executor(config, logging.getLogger('test'))
    kwargs = build.call_args.args[2]
    mount = kwargs['mounts'][0]
    assert mount['Source'] == str(tmp_path)
    assert mount['Target'] == '/mnt/work'
    assert mount['Type'] == 'bind'
    assert 'volumes' not in kwargs


@pytest.mark.parametrize('scope', list(sandbox.SandboxScope))
@pytest.mark.parametrize('workspace_mode', ['legacy', 'bind'])
def test_deployment_bind_mount_uses_docker_host_source(tmp_path, mocker, scope, workspace_mode):
    manager = object.__new__(sandbox.SandboxPoolManager)
    runtime_root = tmp_path / 'runtime-workdir'
    docker_source = tmp_path / 'docker-host' / 'agent workspace'
    config = sandbox.SandboxConfig(
        level=sandbox.SandboxLevel.DOCKER, scope=scope, workspace_mode=workspace_mode,
        container_workspace_root='/mnt/work', failure_policy='error',
        extra_kwargs={'workspace_root': str(runtime_root), 'workspace_volume_name': 'old-workspace'},
        docker_workspace_source=str(docker_source),
    )
    mocker.patch('smolagents.remote_executors.DockerExecutor', Mock())
    mocker.patch.object(sandbox, '_wrap_executor', side_effect=lambda executor, *_: executor)
    mocker.patch.object(sandbox, '_is_containerized_runtime', return_value=False)
    mocker.patch('docker.from_env')
    method = '_build_system_docker_executor' if scope == sandbox.SandboxScope.SYSTEM else '_build_session_docker_executor'
    build = mocker.patch.object(manager, method, return_value=SimpleNamespace())

    manager._build_docker_executor(config, logging.getLogger('test'))

    kwargs = build.call_args.args[2]
    mount, = kwargs['mounts']
    assert mount['Source'] == str(docker_source)
    assert mount['Target'] == ('/mnt/work' if workspace_mode == 'bind' else str(runtime_root))
    assert mount['Type'] == 'bind'
    assert 'volumes' not in kwargs
    assert kwargs['labels']['com.nexent.workspace']
    assert not docker_source.exists()


def test_docker_workspace_source_is_deployment_only():
    config = sandbox.SandboxConfig.from_dict({
        'level': 'docker',
        'docker_workspace_source': '/untrusted/workspace',
    })
    assert config.docker_workspace_source is None


def test_docker_workspace_source_requires_absolute_path(tmp_path):
    with pytest.raises(ValueError, match='absolute'):
        sandbox.SandboxConfig(
            level=sandbox.SandboxLevel.DOCKER,
            docker_workspace_source='relative/workspace',
            extra_kwargs={'workspace_root': str(tmp_path)},
        ).docker_workspace()


def test_deployment_bind_workspace_skips_archive_transfer(tmp_path, mocker):
    resources = WorkspaceResources()
    resources.workspace_path = str(tmp_path)
    resources.sandbox_config = sandbox.SandboxConfig(
        level=sandbox.SandboxLevel.DOCKER,
        docker_workspace_source='/srv/nexent-data/agent-workspace',
        extra_kwargs={'shared_workspace': True},
    )
    container = Mock()
    mocker.patch.object(resources, '_sandbox_containers', return_value=[container])
    grant = mocker.patch.object(resources, '_grant_sandbox_output_access')

    resources._push_file_workspace_to_sandbox()
    resources._pull_file_workspace_from_sandbox()

    grant.assert_called_once_with(container, tmp_path)
    container.put_archive.assert_not_called()
    container.get_archive.assert_not_called()


@pytest.mark.parametrize(
    ('mount_update', 'workspace_label_matches', 'expected'),
    [
        ({}, True, True),
        ({'Type': 'volume'}, True, False),
        ({'Destination': '/mnt/wrong'}, True, False),
        ({'RW': False}, True, False),
        ({'Source': '/srv/other'}, True, False),
        ({}, False, False),
    ],
)
def test_recovery_checks_deployment_bind_mount(mocker, mount_update, workspace_label_matches, expected):
    manager = object.__new__(sandbox.SandboxPoolManager)
    source = '/srv/nexent-data/agent-workspace'
    target = '/mnt/nexent/workdir'
    config = sandbox.SandboxConfig(
        level=sandbox.SandboxLevel.DOCKER, scope=sandbox.SandboxScope.SYSTEM,
        docker_workspace_source=source, extra_kwargs={'workspace_root': target},
    )
    container = Mock(
        status='running',
        short_id='sandbox-id',
        labels={
            'com.nexent.sandbox': 'runtime',
            'com.nexent.workspace': config.docker_workspace().mount_id if workspace_label_matches else 'old',
            sandbox.TLS_LABEL: sandbox.TLS_VERSION,
        },
        attrs={
            'Mounts': [{'Type': 'bind', 'Source': source, 'Destination': target, 'RW': True, **mount_update}],
            'NetworkSettings': {'Ports': {f'{sandbox.SANDBOX_JUPYTER_PORT}/tcp': [
                {'HostIp': '127.0.0.1', 'HostPort': '49173'},
            ]}},
        },
    )
    container.name = sandbox.SANDBOX_CONTAINER_NAME
    mocker.patch('docker.from_env').return_value.containers.list.return_value = [container]
    mocker.patch.object(sandbox, '_is_containerized_runtime', return_value=False)
    tls = mocker.patch.object(sandbox, 'load_container_tls')
    tls.return_value.http.get.return_value.json.return_value = []

    recovered = manager._recover_docker_container(config, logging.getLogger('test'), host_tools_exist=False)

    if expected:
        assert recovered.container is container
        tls.assert_called_once_with(container)
    else:
        assert recovered is None
        tls.assert_not_called()


@pytest.mark.parametrize('scope', list(sandbox.SandboxScope))
@pytest.mark.parametrize('error', [RuntimeError('create failed'), TimeoutError('connect failed')])
def test_strict_creation_failure_never_constructs_local(mocker, scope, error):
    manager = object.__new__(sandbox.SandboxPoolManager)
    config = sandbox.SandboxConfig(level=sandbox.SandboxLevel.DOCKER, scope=scope, failure_policy='error')
    mocker.patch('smolagents.remote_executors.DockerExecutor', Mock())
    mocker.patch.object(sandbox, '_ensure_sandbox_control_network')
    mocker.patch('docker.from_env')
    local = mocker.patch.object(sandbox, '_make_local_executor')
    method = '_build_system_docker_executor' if scope == sandbox.SandboxScope.SYSTEM else '_build_session_docker_executor'
    mocker.patch.object(manager, method, side_effect=error)
    logger = logging.getLogger('test')
    with pytest.raises(RuntimeError, match='fallback is disabled'):
        manager._build_docker_executor(config, logger)
    local.assert_not_called()


def test_tool_paths_roundtrip(tmp_path):
    outputs = tmp_path / 'outputs'
    outputs.mkdir()
    mapping = SandboxWorkspace(tmp_path, '/mnt/run')
    create = CreateFileTool(init_path=str(outputs), observer=None)
    read = ReadFileTool(init_path=str(outputs), observer=None)
    upload = UploadToS3Tool(workspace_path=str(tmp_path))
    for tool in (create, read, upload):
        tool.workspace_mapping = mapping
    result = json.loads(create.forward('/mnt/run/outputs/file.txt', 'hello'))
    assert result['absolute_path'] == '/mnt/run/outputs/file.txt'
    assert 'hello' in read.forward(result['absolute_path'])
    assert upload._upload_path_candidates(result['absolute_path']) == [str(outputs / 'file.txt')]
    assert upload._upload_path_candidates('file.txt')[0] == str(outputs / 'file.txt')


def test_mount_comparison_rejects_wrong_source(tmp_path):
    mapping = SandboxWorkspace(tmp_path, '/mnt/work')
    mount = {'Type': 'bind', 'Source': str(tmp_path), 'Destination': '/mnt/work', 'RW': True}
    assert mapping.matches_mount(mount)
    assert not mapping.matches_mount({**mount, 'Source': str(tmp_path / 'other')})
    assert not mapping.matches_mount({**mount, 'RW': False})


def test_skill_runner_translates_host_working_directory(tmp_path, mocker):
    mapping = SandboxWorkspace(tmp_path, '/mnt/run')
    executor = SimpleNamespace(_nexent_backend='docker', container=Mock())
    runner = sandbox.SandboxSkillScriptRunner(executor, workspace_path=str(tmp_path), workspace_mapping=mapping)
    resolve = mocker.patch.object(runner, '_resolve_workspace_script', side_effect=ValueError('stop after mapping'))
    with pytest.raises(ValueError, match='stop after mapping'):
        runner(
            manager=None, skill_name='', script_path='outputs/probe.py', params=None,
            tenant_id=None, working_directory=str(tmp_path), source='workspace',
        )
    resolve.assert_called_once_with('outputs/probe.py', '/mnt/run')


@pytest.mark.parametrize('value', ['/mnt/run/inputs/secret.txt', '/mnt/run/outputs-other/secret.txt', '../inputs/secret.txt'])
def test_resolve_file_enforces_tool_base(tmp_path, value):
    mapping = SandboxWorkspace(tmp_path, '/mnt/run')
    base = tmp_path / 'outputs'
    with pytest.raises(ValueError):
        mapping.resolve_file(value, base)


def test_resolve_file_rejects_base_outside_workspace(tmp_path):
    mapping = SandboxWorkspace(tmp_path / 'run', '/mnt/run')
    base = tmp_path / 'outside'
    with pytest.raises(ValueError):
        mapping.resolve_file('/mnt/run/outputs/file.txt', base)


def test_resolve_file_accepts_new_nested_targets(tmp_path):
    mapping = SandboxWorkspace(tmp_path, '/mnt/run')
    base = tmp_path / 'outputs'
    target = base / 'new' / 'file.txt'
    assert mapping.resolve_file('new/file.txt', base) == target
    assert mapping.resolve_file('/mnt/run/outputs/new/file.txt', base) == target
    assert not target.exists()


@pytest.mark.parametrize('value', ['link/new.txt', '/mnt/run/outputs/link/new.txt'])
def test_tool_base_rejects_symlink_into_other_workspace_directory(tmp_path, value):
    outputs = tmp_path / 'outputs'
    inputs = tmp_path / 'inputs'
    outputs.mkdir()
    inputs.mkdir()
    try:
        (outputs / 'link').symlink_to(inputs, target_is_directory=True)
    except OSError:
        pytest.skip('Host does not permit symlink creation')
    mapping = SandboxWorkspace(tmp_path, '/mnt/run')
    with pytest.raises(ValueError):
        mapping.resolve_file(value, outputs)


@pytest.mark.parametrize('source', ['/run/desktop/mnt/host/c/work', '/host_mnt/c/work', 'C:/WORK'])
def test_windows_mount_comparison_is_portable(source):
    mapping = SimpleNamespace(host_root=PureWindowsPath('C:/work'), container_root=PurePosixPath('/mnt/work'))
    mount = {'Type': 'bind', 'Source': source, 'Destination': '/mnt/work', 'RW': True}
    assert SandboxWorkspace.matches_mount(mapping, mount)
    assert not SandboxWorkspace.matches_mount(mapping, {**mount, 'Destination': '/mnt/other'})
    assert not SandboxWorkspace.matches_mount(mapping, {**mount, 'Type': 'volume'})


@pytest.mark.parametrize('name', ['NUL', 'CON.txt', 'COM1'])
def test_reserved_windows_names_rejected_on_all_hosts(tmp_path, name):
    mapping = SandboxWorkspace(tmp_path, '/mnt/work')
    with pytest.raises(ValueError, match='Reserved host filename'):
        mapping.to_host('/mnt/work/' + name)


@pytest.mark.parametrize('scope', list(sandbox.SandboxScope))
def test_allowed_creation_failure_keeps_local_fallback(mocker, scope):
    manager = object.__new__(sandbox.SandboxPoolManager)
    config = sandbox.SandboxConfig(level=sandbox.SandboxLevel.DOCKER, scope=scope, failure_policy='local')
    mocker.patch('smolagents.remote_executors.DockerExecutor', Mock())
    mocker.patch.object(sandbox, '_ensure_sandbox_control_network')
    mocker.patch('docker.from_env')
    local = mocker.patch.object(sandbox, '_make_local_executor', return_value=SimpleNamespace())
    wrap = mocker.patch.object(sandbox, '_wrap_executor', side_effect=lambda executor, *_: executor)
    method = '_build_system_docker_executor' if scope == sandbox.SandboxScope.SYSTEM else '_build_session_docker_executor'
    mocker.patch.object(manager, method, side_effect=RuntimeError('create failed'))
    result = manager._build_docker_executor(config, logging.getLogger('test'))
    assert result is local.return_value
    local.assert_called_once()
    wrap.assert_called_once()


@pytest.mark.parametrize('strict', [False, True])
def test_missing_docker_dependency_respects_failure_policy(mocker, strict):
    manager = object.__new__(sandbox.SandboxPoolManager)
    config = sandbox.SandboxConfig(level=sandbox.SandboxLevel.DOCKER, failure_policy='error' if strict else 'local')
    mocker.patch('smolagents.remote_executors.DockerExecutor', None)
    local = mocker.patch.object(sandbox, '_make_local_executor', return_value=SimpleNamespace())
    mocker.patch.object(sandbox, '_wrap_executor', side_effect=lambda executor, *_: executor)
    logger = logging.getLogger('test')
    if strict:
        with pytest.raises(RuntimeError, match='phase=dependency'):
            manager._build_docker_executor(config, logger)
        local.assert_not_called()
    else:
        assert manager._build_docker_executor(config, logger) is local.return_value
