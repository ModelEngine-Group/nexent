# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from pathlib import PurePosixPath
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nexent.core.agents.sandbox_contracts import ScriptProcessResult
from nexent.core.agents.sandbox_kubernetes_runner import KubernetesSkillScriptRunner
from nexent.core.agents.resources.workspace import SandboxWorkspace


@pytest.fixture
def runner(tmp_path, mocker):
    run = tmp_path / ('a' * 32)
    run.mkdir()
    source = tmp_path / 'skill'
    source.mkdir()
    (source / 'run.py').write_text('print(1)')
    access = Mock()
    staged = run / 'skills' / 'invocation' / 'skill'
    access.stage_skill.return_value = staged
    connection = SimpleNamespace(backend=Mock(), owner=Mock(), profile=Mock(), generation='generation')
    executor = SimpleNamespace(_nexent_backend='kubernetes', _container_executor=connection,
                               kernel_id='unique-kernel', _check_execution_cancelled=lambda: None)
    process, cleanup = Mock(), Mock()
    adapter = mocker.patch('nexent.core.agents.sandbox_kubernetes_runner.KubernetesProcessAdapter',
                           side_effect=[process, cleanup])
    process.run.return_value = cleanup.run.return_value = ScriptProcessResult(b'OK', b'', 0)
    mapping = SandboxWorkspace(run, PurePosixPath('/mnt/nexent/workdir/tenant/user/' + run.name))
    instance = KubernetesSkillScriptRunner(executor, workspace_access=access, workspace_path=str(run),
                                          workspace_mapping=mapping, timeout_seconds=5)
    assert adapter.call_args_list[1].args == adapter.call_args_list[0].args
    assert 'check_cancelled' in adapter.call_args_list[0].kwargs
    assert not adapter.call_args_list[1].kwargs
    manager = Mock()
    manager.resolve_skill_script.return_value = (str(source), str(source / 'run.py'), 'run.py')
    return instance, manager, process, access, run


def test_skill_uses_trusted_staging_and_nonroot_process_with_existing_argv(runner):
    instance, manager, process, access, run = runner
    result = instance(manager=manager, skill_name='skill', script_path='run.py', params='"a b" "$(literal)"',
                      tenant_id='tenant', working_directory=str(run))
    assert result == 'OK'
    access.stage_skill.assert_called_once()
    call = process.run.call_args
    assert call.args[0][-2:] == ['a b', '$(literal)']
    assert call.args[0][:4] == ['timeout', '--signal=KILL', '5', 'python']
    assert call.kwargs['cwd'].endswith('/outputs')
    assert call.kwargs['env']['NEXENT_WORKSPACE'] == instance._workspace_path
    assert call.kwargs['env']['PNPM_CONFIG_OFFLINE'] == 'true'
    assert 'user' not in call.kwargs


@pytest.mark.parametrize('exit_code,stderr,expected', [(7, b'script-error', 'script-error'), (0, b'', None)])
def test_script_error_keeps_existing_tool_result_contract(runner, exit_code, stderr, expected):
    instance, manager, process, _, run = runner
    process.run.side_effect = [ScriptProcessResult(b'', b'', 0), ScriptProcessResult(b'output', stderr, exit_code)]
    result = instance(manager=manager, skill_name='skill', script_path='run.py', params='', tenant_id='tenant',
                      working_directory=str(run))
    if expected:
        assert json.loads(result) == {'error': expected, 'output': 'output'}
    else:
        assert result == 'output'


@pytest.mark.parametrize('status', [124, 137])
def test_timeout_is_not_retried(runner, status):
    instance, manager, process, _, run = runner
    process.run.side_effect = [ScriptProcessResult(b'', b'', 0), ScriptProcessResult(b'', b'', status)]
    with pytest.raises(TimeoutError):
        instance(manager=manager, skill_name='skill', script_path='run.py', params='', tenant_id='tenant',
                 working_directory=str(run))
    assert process.run.call_count == 2


def test_runner_rejects_root_and_wrong_workspace(runner):
    instance, _, process, _, _ = runner
    with pytest.raises(PermissionError):
        instance._execute_process(['true'], user='0')
    with pytest.raises(RuntimeError):
        instance._resolve_skills_root('/other-run')
    process.run.assert_not_called()


def test_cleanup_is_limited_to_this_invocation(runner):
    instance, _, _, access, run = runner
    instance.cleanup()
    access.cleanup_skills.assert_called_once_with(str(run), instance._invocation)


def test_runner_rejects_unscoped_staging_and_nonwritable_outputs(runner):
    instance, _, process, _, _ = runner
    with pytest.raises(ValueError, match='staging root'):
        instance._stage_skill_directory('/source', 'skill', '/foreign')
    with pytest.raises(ValueError, match='output directory'):
        instance._ensure_output_directory('/foreign')
    process.run.return_value = ScriptProcessResult(b'', b'denied', 1)
    with pytest.raises(PermissionError, match='not writable'):
        instance._ensure_output_directory(instance._workspace_path + '/outputs')


def test_online_store_is_seeded_once_per_invocation_and_removed_at_cleanup(runner):
    instance, _, process, access, run = runner
    instance._ensure_network_pnpm_store(instance._workspace_path)
    store = instance._pnpm_store_path
    instance._ensure_network_pnpm_store(instance._workspace_path)
    assert process.run.call_count == 1
    assert store.startswith('/tmp/nexent-pnpm-stores/') and len(store.rsplit('/', 1)[1]) == 24
    run.rmdir()
    instance.cleanup()
    cleanup_call = instance._cleanup_process.run.call_args
    assert cleanup_call.args[0][-1] == store.rsplit('/', 1)[1]
    assert cleanup_call.kwargs == {'cwd': '/', 'env': {}, 'timeout_seconds': 5}
    assert process.run.call_count == 1
    access.cleanup_skills.assert_called_once_with(str(run), instance._invocation)


def test_failed_store_seed_is_not_marked_ready(runner):
    instance, _, process, _, _ = runner
    process.run.return_value = ScriptProcessResult(b'', b'seed failed', 1)
    with pytest.raises(RuntimeError, match='prepare nonroot'):
        instance._ensure_network_pnpm_store(instance._workspace_path)
    assert not instance._pnpm_store_seeded


@pytest.mark.parametrize('failure', ['exit', 'transport'])
def test_cleanup_attempts_both_resources_and_logs_failure(runner, caplog, failure):
    instance, _, _, access, _ = runner
    instance._resolve_network_pnpm_store(instance._workspace_path)
    access.cleanup_skills.side_effect = OSError('local cleanup failed')
    if failure == 'transport':
        instance._cleanup_process.run.side_effect = TimeoutError('cleanup timed out')
    else:
        instance._cleanup_process.run.return_value = ScriptProcessResult(b'', b'failure', 1)
    instance.cleanup()
    instance._cleanup_process.run.assert_called_once()
    assert 'Kubernetes Skill staging cleanup failed' in caplog.text
    assert 'Kubernetes pnpm store cleanup' in caplog.text
