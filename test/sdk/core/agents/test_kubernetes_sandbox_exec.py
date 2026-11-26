# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from contextlib import nullcontext
from unittest.mock import Mock

import pytest

from nexent.core.agents.sandbox_contracts import SandboxOwner, SystemSandboxProfile
from nexent.core.agents.sandbox_kubernetes_exec import KubernetesProcessAdapter


@pytest.fixture
def process(mocker):
    api = Mock()
    api.read_namespaced_pod.return_value = {}
    backend = Mock()
    backend.api_factory.side_effect = lambda: nullcontext(api)
    backend.resource_name.return_value = 'owned-sandbox'
    backend.generation.return_value = 'pod:container:0'
    backend.manifests.return_value = ({}, {})
    owner = SandboxOwner('test', 'namespace', 'runtime', 'uid', '10.0.0.1', 'epoch')
    profile = SystemSandboxProfile('sandbox:image', 'claim')
    ws = Mock()
    ws.is_open.return_value = False
    ws.read_stdout.return_value = b'out'
    ws.read_stderr.return_value = b'error'
    ws.returncode = 7
    stream = mocker.patch('nexent.core.agents.sandbox_kubernetes_exec.stream', return_value=ws)
    adapter = KubernetesProcessAdapter(backend, owner, profile, 'pod:container:0')
    return adapter, backend, ws, stream


def test_real_exit_channels_and_fixed_nonroot_command(process):
    adapter, _, ws, stream = process
    result = adapter.run(['python', 'a b.py', '$(literal)'], cwd='/mnt/nexent/workdir/run',
                         env={'VALUE': 'x y'}, timeout_seconds=5)
    assert (result.stdout, result.stderr, result.exit_code) == (b'out', b'error', 7)
    kwargs = stream.call_args.kwargs
    assert kwargs['container'] == 'sandbox' and kwargs['tty'] is False and kwargs['stdin'] is False
    assert 'user' not in kwargs and 'environment' not in kwargs and 'workdir' not in kwargs
    command = kwargs['command']
    assert command[:4] == ['timeout', '--signal=TERM', '--kill-after=2', '5.0']
    payload = json.loads(command[-1])
    assert payload == {'argv': ['python', 'a b.py', '$(literal)'], 'cwd': '/mnt/nexent/workdir/run',
                       'env': {'VALUE': 'x y'}}
    ws.close.assert_called_once()


def test_generation_change_prevents_exec(process):
    adapter, backend, _, stream = process
    backend.generation.return_value = 'replacement'
    with pytest.raises(RuntimeError, match='generation'):
        adapter.run(['true'], cwd='/tmp', env={}, timeout_seconds=1)
    stream.assert_not_called()


def test_transport_failure_is_not_replayed(process):
    adapter, _, _, stream = process
    stream.side_effect = RuntimeError('connection lost after send')
    with pytest.raises(RuntimeError, match='connection lost'):
        adapter.run(['true'], cwd='/tmp', env={}, timeout_seconds=1)
    assert stream.call_count == 1


def test_cancelled_stream_is_closed_without_retry(process):
    adapter, _, ws, stream = process
    ws.is_open.return_value = True
    adapter.check_cancelled = Mock(side_effect=[None, RuntimeError('cancelled')])
    with pytest.raises(RuntimeError, match='cancelled'):
        adapter.run(['true'], cwd='/tmp', env={}, timeout_seconds=1)
    ws.close.assert_called_once()
    assert stream.call_count == 1


@pytest.mark.parametrize('argv,cwd,env,timeout', [([], '/tmp', {}, 1), (['true'], 'relative', {}, 1),
                                               (['true'], '/tmp', {'A=B': 'x'}, 1),
                                               (['true'], '/tmp', {}, 0), (['true'], '/tmp', {}, float('inf'))])
def test_invalid_process_parameters_do_not_exec(process, argv, cwd, env, timeout):
    adapter, _, _, stream = process
    with pytest.raises(ValueError):
        adapter.run(argv, cwd=cwd, env=env, timeout_seconds=timeout)
    stream.assert_not_called()


def test_definitive_exit_releases_process_lifetime(process):
    adapter, _, _, _ = process
    lifetime = Mock()
    lifetime.begin.return_value = 'process:holder'
    adapter.run_lifecycle = lifetime
    adapter.run(['false'], cwd='/tmp', env={}, timeout_seconds=1)
    lifetime.begin.assert_called_once_with('process')
    lifetime.finish.assert_called_once_with('process:holder')
    lifetime.unknown.assert_not_called()


@pytest.mark.parametrize('failure', ['connect', 'cancel', 'missing_status', 'output_limit'])
def test_uncertain_process_keeps_reservation_without_replay(process, failure):
    adapter, _, ws, stream = process
    lifetime = Mock()
    lifetime.begin.return_value = 'process:holder'
    adapter.run_lifecycle = lifetime
    if failure == 'connect':
        stream.side_effect = RuntimeError('lost response after exec request')
    elif failure == 'cancel':
        ws.is_open.return_value = True
        adapter.check_cancelled = Mock(side_effect=[None, RuntimeError('cancelled')])
    elif failure == 'missing_status':
        ws.returncode = None
    else:
        ws.read_stdout.return_value = b'x' * (16 * 1024 * 1024 + 1)
    with pytest.raises(RuntimeError):
        adapter.run(['python', 'business.py'], cwd='/tmp', env={}, timeout_seconds=1)
    lifetime.begin.assert_called_once_with('process')
    lifetime.unknown.assert_called_once_with('process:holder')
    lifetime.finish.assert_not_called()
    assert stream.call_count == 1


def test_preflight_failure_does_not_retain_process_lifetime(process):
    adapter, backend, _, stream = process
    adapter.run_lifecycle = lifetime = Mock()
    backend.generation.return_value = 'replacement'
    with pytest.raises(RuntimeError, match='generation'):
        adapter.run(['true'], cwd='/tmp', env={}, timeout_seconds=1)
    lifetime.begin.assert_not_called()
    stream.assert_not_called()


def test_observed_exit_releases_even_if_final_generation_check_fails(process):
    adapter, backend, ws, _ = process
    adapter.run_lifecycle = lifetime = Mock()
    backend.generation.side_effect = [adapter.generation, 'replacement']
    with pytest.raises(RuntimeError, match='generation'):
        adapter.run(['true'], cwd='/tmp', env={}, timeout_seconds=1)
    lifetime.finish.assert_called_once_with(lifetime.begin.return_value)
    lifetime.unknown.assert_not_called()
    ws.close.assert_called_once()


def test_streamed_channels_are_collected_before_definitive_exit(process):
    adapter, _, ws, _ = process
    ws.is_open.side_effect = [True, False]
    ws.read_stdout.side_effect = [b'first', b'last']
    ws.read_stderr.side_effect = [b'warning', b'']
    result = adapter.run(['true'], cwd='/tmp', env={}, timeout_seconds=1)
    assert result.stdout == b'firstlast' and result.stderr == b'warning'
    ws.update.assert_called_once()
    ws.close.assert_called_once()


@pytest.mark.parametrize('failure', ['deadline', 'output_limit'])
def test_active_stream_bounds_leave_execution_unknown_without_replay(process, monkeypatch, failure):
    import nexent.core.agents.sandbox_kubernetes_exec as module

    adapter, _, ws, stream = process
    lifetime = adapter.run_lifecycle = Mock()
    ws.is_open.return_value = True
    if failure == 'deadline':
        monkeypatch.setattr(module.time, 'monotonic', Mock(side_effect=[0, 10]))
        expected = TimeoutError
    else:
        ws.read_stdout.return_value = b'x' * (16 * 1024 * 1024 + 1)
        expected = RuntimeError
    with pytest.raises(expected):
        adapter.run(['true'], cwd='/tmp', env={}, timeout_seconds=1)
    lifetime.unknown.assert_called_once_with(lifetime.begin.return_value)
    lifetime.finish.assert_not_called()
    assert stream.call_count == 1
    ws.close.assert_called_once()
