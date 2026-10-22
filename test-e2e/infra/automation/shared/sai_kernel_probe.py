# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""SAI-D3-001: real Docker execution with a deterministic model provider."""
import argparse
import asyncio
import hashlib
import inspect
import json
import logging
import re
import secrets
import threading
from pathlib import Path

from nexent.core.agents import agent_model, nexent_agent, sandbox, subagent_wrapper
from nexent.core.agents.agent_model import AgentConfig
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.agents.sandbox import SandboxConfig, SandboxLevel, SandboxScope
from nexent.core.concurrency import LanePolicy, ThreadManager, cancellation
from nexent.core.concurrency.cancellation import RunCancellationScope
from nexent.core.concurrency.context import (
    _reset_current_thread_manager,
    _set_current_thread_manager,
)
from nexent.core.model_errors import ModelErrorCode, ModelInvocationTerminalError
from nexent.core.tools.parallel_executor import _parallel_executor
from nexent.core.utils.observer import MessageObserver
from smolagents.models import ChatMessage, Model

import docker


def run_probe(batches=1, expected_sources=None, scope_name='session'):
    """Exercise actual CoreAgent instances, kernels and owner cleanup."""
    records, starts, ends, warnings = [], [], [], []
    barrier = threading.Barrier(2)
    skill_workspace = '/home/sandbox/workdir/sai-regression'

    class Capture(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.WARNING:
                warnings.append(record.getMessage())

    class ControlledModel(Model):
        def __init__(self):
            super().__init__()
            self.model_id = 'controlled-sai'
            self.calls = 0

        def generate(self, messages, **kwargs):
            text = str(messages)
            if 'TASK_MARKER=FAIL' in text:
                raise ModelInvocationTerminalError(ModelErrorCode.TIMEOUT, attempts=1)
            self.calls += 1
            if self.calls > 1:
                measurements = re.findall(r'\{"marker": "(?:LEFT|RIGHT)", "start": [0-9.]+, "end": [0-9.]+\}', text)
                assert measurements, 'The real kernel must return its measured execution window'
                return ChatMessage(role='assistant', content=f'<final_answer>{measurements[-1]}</final_answer>')
            marker = 'LEFT' if 'TASK_MARKER=LEFT' in text else 'RIGHT'
            barrier.wait(timeout=30)
            return ChatMessage(role='assistant', content=(
                "<code>\nimport time\nimport json\n"
                "assert 'probe_marker' not in globals()\n"
                f"probe_marker = {marker!r}\nstarted = time.time()\ntime.sleep(1)\n"
                "json.dumps({'marker': probe_marker, 'start': started, 'end': time.time()})\n</code>"
            ))

    class ControlledFactory(NexentAgent):
        def create_model(self, name):
            return ControlledModel()

        def create_single_agent(self, config, **kwargs):
            agent = super().create_single_agent(config, **kwargs)
            lease = agent.python_executor
            assert getattr(lease, '_nexent_kernel_lease', False), 'Docker fallback is forbidden'
            for runner in self._sandbox_skill_runners:
                runner._resolve_skills_root(skill_workspace)
            records.append({'agent': agent, 'lease': lease, 'kernel': lease.kernel_id})
            return agent

    fingerprints = {
        module.__name__: hashlib.sha256(Path(inspect.getfile(module)).read_bytes()).hexdigest()
        for module in (nexent_agent, sandbox, subagent_wrapper, agent_model, cancellation)
    }
    if expected_sources:
        assert fingerprints == expected_sources, 'Image source differs from worktree'
    manager = ThreadManager('sai-docker', {
        'model-tool-io': LanePolicy('model-tool-io', 4, 8),
        'sandbox': LanePolicy('sandbox', 8, 16),
        'background-service': LanePolicy('background-service', 2, 4),
    })
    manager.start()
    token = _set_current_thread_manager(manager)
    capture = Capture()
    logging.getLogger().addHandler(capture)
    observer = MessageObserver()
    observer.add_subagent_start = lambda **kw: starts.append(kw)
    observer.add_subagent_end = lambda **kw: ends.append(kw)
    scope = RunCancellationScope()
    previous_container_name = sandbox.SANDBOX_CONTAINER_NAME
    if scope_name == 'system':
        # Never recover or remove the business runtime's shared sandbox.
        sandbox.SANDBOX_CONTAINER_NAME = 'nexent-sai-system-' + secrets.token_hex(6)
    # This probe measures real kernel lifetimes from construction; TFP cases cover deferred activation.
    factory = ControlledFactory(observer, [], scope.stop_event, cancellation_scope=scope,
        tool_fastpath_enabled=False,
        sandbox_config=SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope(scope_name),
            timeout_seconds=30, auto_sync_outputs=False))
    container = None
    results = []
    client = docker.from_env()
    try:
        child = AgentConfig(name='child', description='Concurrent worker', model_name='controlled', tools=[], max_steps=2)
        root = factory.create_single_agent(AgentConfig(name='parent', description='Parent',
            model_name='controlled', tools=[], worker_agents=[child]))
        factory.set_agent(root)
        assert len(records) == 1, 'Child resources must be lazy'
        parent_lease = records[0]['lease']
        container = parent_lease.container
        skill_script = skill_workspace + '/skills/shared/run.py'
        staged = container.exec_run(['python', '-c',
            f"from pathlib import Path; p=Path({skill_script!r}); p.parent.mkdir(parents=True); p.write_text('print(1)')"])
        assert staged.exit_code == 0, staged.output
        factory._sandbox_skill_runners[0]._staged_skills['shared'] = str(Path(skill_script).parent)
        # Fail after allocating a real child kernel, then recover on the same definition.
        failed_offset = len(records)
        try:
            root.managed_agents['child'](task='TASK_MARKER=FAIL')
        except ModelInvocationTerminalError:
            pass
        else:
            raise AssertionError('Controlled failed invocation unexpectedly succeeded')
        failed_records = records[failed_offset:]
        assert len(failed_records) == 1
        response = parent_lease._requests.get(parent_lease.base_url + '/api/kernels', timeout=5)
        response.raise_for_status()
        assert {r['id'] for r in response.json()} == {parent_lease.kernel_id}
        assert not failed_records[0]['lease']._unhealthy
        for batch in range(batches):
            offset = len(records)
            output = _parallel_executor([
                (root.managed_agents['child'], {'task': 'TASK_MARKER=LEFT'}, 'left'),
                (root.managed_agents['child'], {'task': 'TASK_MARKER=RIGHT'}, 'right'),
            ], timeout=120, max_workers=2)
            pair = records[offset:]
            assert len(pair) == 2 and len({r['kernel'] for r in pair}) == 2
            assert pair[0]['agent'] is not pair[1]['agent']
            assert pair[0]['agent'].model is not pair[1]['agent'].model
            measurements = []
            for key in ('left', 'right'):
                answer = str(output[key]).rsplit('\n', 1)[-1]
                if answer.startswith('<final_answer>') and answer.endswith('</final_answer>'):
                    answer = answer[len('<final_answer>'):-len('</final_answer>')]
                measurements.append(json.loads(answer))
            assert [value['marker'] for value in measurements] == ['LEFT', 'RIGHT'], output
            assert max(value['start'] for value in measurements) < min(value['end'] for value in measurements)
            assert all(not r['lease']._unhealthy for r in pair)
            assert all(r['kernel'] == r['lease'].kernel_id for r in pair), 'Unexpected kernel replacement'
            response = parent_lease._requests.get(parent_lease.base_url + '/api/kernels', timeout=5)
            response.raise_for_status()
            assert {r['id'] for r in response.json()} == {parent_lease.kernel_id}, response.text
            cached_script = container.exec_run(['cat', skill_script])
            assert cached_script.exit_code == 0 and cached_script.output == b'print(1)', cached_script.output
            results.append({'batch': batch, 'kernels': [r['kernel'] for r in pair],
                'results': output, 'peak_active_executions': 2, 'execution_windows': measurements})
        logs = container.logs().decode(errors='replace')
        assert 'Replacing stale connection' not in logs, logs
        assert not any('unhealthy' in line.lower() for line in warnings), warnings
        assert len(starts) == len(ends) == 2 * batches + 1
        assert {r['invocation_id'] for r in starts} == {r['invocation_id'] for r in ends}
    finally:
        try:
            factory._close_subagent_invocations()
            factory._cleanup_sandbox()
            if container is not None and scope_name == 'session':
                try:
                    client.containers.get(container.id)
                except docker.errors.NotFound:
                    pass
                else:
                    raise AssertionError('Owned session sandbox container remains')
            if container is not None and scope_name == 'system':
                response = parent_lease._requests.get(parent_lease.base_url + '/api/kernels', timeout=5)
                response.raise_for_status()
                assert response.json() == [], 'Owned kernels remain after root release'
        finally:
            logging.getLogger().removeHandler(capture)
            sandbox.SandboxPoolManager.get_instance().shutdown(logging.getLogger('sai'))
            if container is not None:
                try:
                    client.containers.get(container.id)
                except docker.errors.NotFound:
                    pass
                else:
                    raise AssertionError('Owned sandbox remains after pool shutdown')
            sandbox.SANDBOX_CONTAINER_NAME = previous_container_name
            _reset_current_thread_manager(token)
            asyncio.run(manager.shutdown(timeout=10))
            client.close()
    return {'batches': results, 'successful_invocations': 2 * batches,
        'failed_invocations': 1, 'recovered_after_failure': True,
        'source_fingerprints': fingerprints, 'unhealthy': 0, 'replacements': 0, 'leftovers': 0,
        'scope': scope_name,
        'profile': 'mock model / real CoreAgent, parallel tool, Docker Gateway'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--batches', type=int, default=1)
    parser.add_argument('--expected-sources')
    parser.add_argument('--scope', choices=['session', 'system'], default='session')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    expected = json.loads(Path(args.expected_sources).read_text()) if args.expected_sources else None
    result = run_probe(args.batches, expected, args.scope)
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False))
