# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Controlled model boundary around real Runtime, Agent and Kubernetes paths."""

import asyncio
import html
import json
import re
import shlex
import shutil
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import uvicorn
from fastapi import HTTPException, Request
from infrastructure.concurrency import runtime_thread_manager
from runtime.adapters.nexent.sandbox import get_runtime_sandbox_options, resolve_sandbox_config
from runtime.api.application import app
from runtime.sandbox_runtime import get_coordinator
from runtime.sandbox_services import bind_runtime_sandbox
from smolagents.models import ChatMessage, Model
from smolagents.tools import Tool

from nexent.core.agents.contracts.config import AgentConfig, ToolConfig
from nexent.core.agents.cores.smolagents.agent import NexentAgent
from nexent.core.agents.sandbox_kubernetes_runner import KubernetesSkillScriptRunner
from nexent.core.concurrency import ManagedTaskSpec, RunCancellationScope
from nexent.core.tools.parallel_executor import _parallel_executor
from nexent.core.utils.observer import MessageObserver


callbacks = []


def script_matrix(parent, config, workspace, run_id):
    source = Path('/tmp/ksm-skills') / run_id
    source.mkdir(parents=True)
    files = {
        'run.py': "import json,os,sys\nprint(json.dumps({'args':sys.argv[1:],'cwd':os.getcwd(),'env':os.environ.get('NEXENT_OUTPUT_DIR'),'state':globals().get('marker_value','ABSENT')}))\n",
        'run.sh': '#!/bin/bash\r\nprintf "SH_OK\\n"\r\n',
        'fail.py': "import sys\nprint('EXPECTED_STDOUT')\nprint('EXPECTED_STDERR',file=sys.stderr)\nsys.exit(7)\n",
        'slow.py': "import time\nopen('timeout-count','a').write('X')\ntime.sleep(5)\n",
        'offline.sh': '#!/bin/bash\nset -eu\nmkdir -p "$NEXENT_OUTPUT_DIR/offline-project"\n'
            + 'printf \'{"dependencies":{"clsx":"2.1.1"}}\' > "$NEXENT_OUTPUT_DIR/offline-project/package.json"\n'
            + 'pnpm --dir "$NEXENT_OUTPUT_DIR/offline-project" install --offline --ignore-scripts --reporter=silent\n'
            + 'node -e "console.log(require(process.env.NEXENT_OUTPUT_DIR + \'/offline-project/node_modules/clsx\')(\'OFFLINE_OK\'))"\n',
    }
    for name, content in files.items():
        (source / name).write_bytes(content.encode())
    (workspace / 'outputs' / 'work.py').write_text("print('WORKSPACE_PY_OK')")
    (workspace / 'outputs' / 'work.js').write_text("console.log('JS_OK',typeof require('docx').Document)")
    (workspace / 'outputs' / 'work.mjs').write_text(
        "import {createRequire} from 'module';const require=createRequire(import.meta.url);console.log('MJS_OK',typeof require('docx').Document)")
    manager = SimpleNamespace(resolve_skill_script=lambda name, script, tenant_id: (str(source), str(source / script), script),
                              resolve_skill_dir=lambda name, tenant_id: str(source))
    runner = KubernetesSkillScriptRunner(parent, workspace_access=config.workspace_access,
        workspace_path=str(workspace), workspace_mapping=config.bind_workspace().for_run(str(workspace)),
        timeout_seconds=10, network_enabled=not config.network_disabled)
    try:
        def run(script, *, origin='skill', params=''):
            return runner(manager=manager, skill_name='fixture', script_path=script, params=params,
                tenant_id='fixture-tenant', working_directory=str(workspace), source=origin)

        python_result = json.loads(run('run.py', params=shlex.join(['a b', "quote'part"])))
        mapping = config.bind_workspace().for_run(str(workspace))
        assert python_result == {'args': ['a b', "quote'part"], 'cwd': str(mapping.container_root / 'outputs'),
                                 'env': str(mapping.container_root / 'outputs'), 'state': 'ABSENT'}
        assert run('run.sh').strip() == 'SH_OK'
        assert (source / 'run.sh').read_bytes().count(b'\r\n') == 2
        assert run('outputs/work.py', origin='workspace').strip() == 'WORKSPACE_PY_OK'
        assert run('outputs/work.js', origin='workspace').strip() == 'JS_OK function'
        assert run('outputs/work.mjs', origin='workspace').strip() == 'MJS_OK function'
        assert run('offline.sh').strip() == 'OFFLINE_OK'
        failure = json.loads(run('fail.py'))
        assert 'EXPECTED_STDERR' in failure['error'] and 'EXPECTED_STDOUT' in failure['output']
        runner._timeout_seconds = 1
        try:
            run('slow.py')
        except TimeoutError:
            pass
        else:
            raise AssertionError('A timed out script was reported successful')
        assert (workspace / 'outputs' / 'timeout-count').read_text() == 'X'
        store = config.system_profile.container_workspace_root + '/.pnpm-store'
        seed = runner._process.run(['python', '-c',
            "import os,sys;from pathlib import Path;p=Path(sys.argv[1]);assert (p/'v3').is_dir();assert not os.access(p,os.W_OK);print('SEED_OK')", store],
            cwd=str(mapping.container_root / 'outputs'), env={}, timeout_seconds=5)
        assert seed.exit_code == 0 and seed.stdout.strip() == b'SEED_OK'
        if not config.network_disabled:
            check = runner._process.run(['test', '-w', runner._pnpm_store_path],
                cwd=str(mapping.container_root / 'outputs'), env={}, timeout_seconds=5)
            assert check.exit_code == 0
        assert parent.run_code_raise_errors('marker_value').output == '37'
        return {'scripts': ['skill.py', 'skill.sh', 'workspace.py', 'workspace.js', 'workspace.mjs'],
                'argv_cwd_env': True, 'separate_python_process': True, 'stderr_nonzero': True,
                'timeout_once': True, 'original_crlf_preserved': True, 'full_readonly_seed': True,
                'online_store_writable': not config.network_disabled}
    finally:
        runner._timeout_seconds = 10
        runner.cleanup()
        shutil.rmtree(source)


@app.middleware('http')
async def observe_callback(request, call_next):
    response = await call_next(request)
    if request.url.path == '/internal/sandbox/tool-invoke':
        callbacks.append(response.status_code)
    return response


def probe_core(owned):
    coordinator = get_coordinator()
    run_id = uuid.uuid4().hex
    scope = RunCancellationScope()
    owned['scope'] = scope
    lease = coordinator.reserve('fixture-tenant', 'fixture-user', 'fixture:' + run_id, run_id,
                                kind='DEBUG', cancel=scope.cancel)
    owned['lease'] = lease
    coordinator.activate(lease)
    options = get_runtime_sandbox_options()
    config = resolve_sandbox_config(None, None, workspace_mode='bind',
        container_workspace_root='/mnt/nexent/workdir', failure_policy='error', **options)
    config.auto_sync_outputs = False
    bind_runtime_sandbox(config, execution_run_id=run_id)
    workspace = config.workspace_access.prepare_run('fixture-tenant', 'fixture-user', run_id)
    coordinator.record_workspace(run_id, workspace)
    (workspace / 'outputs' / 'owner.txt').write_text(coordinator.owner.pod_uid)
    config.workspace_access.seal_materials(workspace)
    created, contexts, observed_kernels, windows = [], [], [], []
    barrier = threading.Barrier(2)

    class ControlledModel(Model):
        def __init__(self):
            super().__init__()
            self.model_id = 'controlled-ksm'
            self.calls = 0
            self.child_marker = None

        def generate(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                text = str(messages)
                if 'CASE_CANCEL_CHILD' in text:
                    return ChatMessage(role='assistant', content=(
                        "<code>import time\nopen('cancel.started','w').write('started')\ntime.sleep(30)</code>"))
                if 'CASE_CHILD_' in text:
                    self.child_marker = 'LEFT' if 'CASE_CHILD_LEFT' in text else 'RIGHT'
                return ChatMessage(role='assistant', content=(
                    '<code>import time\nmarker_value = 37\nksm_started = time.time()\n'
                    + ('fixture_barrier()\ntime.sleep(0.1)\n' if self.child_marker else '') + 'marker_value</code>'))
            if self.calls == 2:
                for agent in created:
                    remote = getattr(agent.python_executor, 'remote', None) or agent.python_executor
                    if agent.model is self:
                        observed_kernels.append(remote.kernel_id)
                    bridge = getattr(remote, '_nexent_tool_bridge', None)
                    if bridge is not None and not getattr(bridge, '_fixture_observed', False):
                        original_context = bridge.execution_context
                        @contextmanager
                        def observed_context(original=original_context):
                            with original() as execution_id:
                                contexts.append(execution_id)
                                yield execution_id
                        bridge.execution_context = observed_context
                        bridge._fixture_observed = True
                return ChatMessage(role='assistant', content=(
                    '<code>import json\nassert marker_value == 37\n'
                    "owner_value = json.loads(read_file(file_path='owner.txt'))['content']\n"
                    f'assert owner_value == {coordinator.owner.pod_uid!r}\n'
                    + (f"json.dumps({{'ksm_child': {self.child_marker!r}, 'start': ksm_started, 'end': time.time()}})"
                       if self.child_marker else 'owner_value') + '</code>'))
            if self.child_marker:
                found = re.findall(r'\{"ksm_child": "(?:LEFT|RIGHT)", "start": [0-9.]+, "end": [0-9.]+\}',
                                   html.unescape(str(messages)))
                assert found, 'The real child kernel must report its execution window'
                windows.append(json.loads(found[-1]))
            return ChatMessage(role='assistant', content='<final_answer>' + coordinator.owner.pod_uid + '</final_answer>')

    class BarrierTool(Tool):
        name = 'fixture_barrier'
        description = 'Wait for both controlled child kernel requests.'
        inputs = {}
        output_type = 'string'

        def forward(self):
            barrier.wait(timeout=30)
            return 'RELEASED'

    class ControlledFactory(NexentAgent):
        def create_model(self, name):
            return ControlledModel()

        def create_tool(self, tool_config):
            if tool_config.class_name == 'ControlledBarrierTool':
                tool = BarrierTool()
                tool._nexent_execute_on_host = True
                return tool
            return super().create_tool(tool_config)

        def create_single_agent(self, *args, **kwargs):
            agent = super().create_single_agent(*args, **kwargs)
            created.append(agent)
            return agent

    factory = ControlledFactory(MessageObserver(), [], scope.stop_event, cancellation_scope=scope,
        sandbox_config=config, workspace_path=str(workspace), workspace_run_id=run_id,
        user_id='fixture-user', tenant_id='fixture-tenant', tool_fastpath_enabled=True)
    tool = ToolConfig(class_name='ReadFileTool', name='read_file', params={'init_path': str(workspace / 'outputs')})
    barrier_tool = ToolConfig(class_name='ControlledBarrierTool', name='fixture_barrier', params={})
    child = AgentConfig(name='child', description='Controlled child', model_name='controlled',
                        tools=[tool, barrier_tool], max_steps=3)
    root = factory.create_single_agent(AgentConfig(name='parent', description='Controlled parent',
        model_name='controlled', tools=[tool], worker_agents=[child], max_steps=3))
    factory.set_agent(root)
    assert getattr(root.python_executor, 'remote', None) is None
    backend = config.runtime_backend
    callback_start = len(callbacks)
    try:
        # All twenty real acquisitions use bounded Runtime-owned workers.
        original_factory = backend.api_factory
        lost = threading.Event()
        @contextmanager
        def lost_response_factory():
            with original_factory() as api:
                original_create = api.create_namespaced_pod
                def create_then_lose(*args, **kwargs):
                    response = original_create(*args, **kwargs)
                    if not lost.is_set():
                        lost.set()
                        raise TimeoutError('Controlled lost create response after API commit')
                    return response
                api.create_namespaced_pod = create_then_lose
                yield api
        backend.api_factory = lost_response_factory
        with original_factory() as api:
            candidate = backend.manifests(config.owner, config.system_profile)[1]
            candidate['metadata']['name'] = 'fixture-foreign-' + uuid.uuid4().hex[:12]
            actual = api.create_namespaced_service(config.owner.namespace,
                {'metadata': {'name': candidate['metadata']['name']}, 'spec': candidate['spec']})
            try:
                backend.create_or_confirm(api, 'service', config.owner.namespace, candidate)
            except RuntimeError:
                assert api.read_namespaced_service(actual.metadata.name, config.owner.namespace).metadata.uid == actual.metadata.uid
            else:
                raise AssertionError('An unowned resource was adopted')
            finally:
                api.delete_namespaced_service(actual.metadata.name, config.owner.namespace,
                                             body={'preconditions': {'uid': actual.metadata.uid}})
        futures = [runtime_thread_manager.submit('sandbox',
            ManagedTaskSpec(task_name='fixture-first-acquisition', owner='ksm-test', run_id=run_id),
            backend.ensure_system, config.owner, config.system_profile).future for _ in range(20)]
        connections = [future.result(timeout=130) for future in futures]
        backend.api_factory = original_factory
        assert len({id(connection) for connection in connections}) == 1
        root.run('controlled runtime callback')
        parent = getattr(root.python_executor, 'remote', None) or root.python_executor
        assert parent._nexent_backend == 'kubernetes'
        assert not hasattr(parent, 'container')
        assert parent.run_code_raise_errors('marker_value').output == '37'
        parent_kernel = parent.kernel_id
        result = _parallel_executor([(root.managed_agents['child'], {'task': 'CASE_CHILD_LEFT'}, 'left'),
                                    (root.managed_agents['child'], {'task': 'CASE_CHILD_RIGHT'}, 'right')],
                                   timeout=90, max_workers=2)
        assert all(coordinator.owner.pod_uid in str(value) for value in result.values()), result
        assert parent.run_code_raise_errors('marker_value').output == '37'
        assert parent.kernel_id == parent_kernel
        assert len(set(observed_kernels)) == 3
        assert len(windows) == 2 and max(w['start'] for w in windows) < min(w['end'] for w in windows)
        cancel_future = runtime_thread_manager.submit('model-tool-io',
            ManagedTaskSpec(task_name='fixture-cancel-child', owner='ksm-test', run_id=run_id),
            root.managed_agents['child'], task='CASE_CANCEL_CHILD').future
        cancel_deadline = time.monotonic() + 10
        while not (workspace / 'outputs' / 'cancel.started').exists():
            assert time.monotonic() < cancel_deadline, 'The real child never entered its blocking code'
            time.sleep(0.1)
        with factory._subagent_invocations_lock:
            active_scopes = list(factory._subagent_invocations.values())
        assert len(active_scopes) == 1
        active_scopes[0].cancel()
        try:
            cancel_future.result(timeout=8)
        except BaseException as exc:
            from concurrent.futures import CancelledError

            from nexent.core.concurrency.cancellation import RunTerminated
            assert isinstance(exc, (CancelledError, RunTerminated)), type(exc).__name__
        assert parent.run_code_raise_errors('marker_value').output == '37'
        remaining = connections[0].tls_client.http.get(connections[0].base_url + '/api/kernels', timeout=5)
        assert {kernel['id'] for kernel in remaining.json()} == {parent_kernel}
        scripts = script_matrix(parent, config, workspace, run_id)
        bridge = parent._nexent_tool_bridge
        authorization = 'Bearer ' + bridge._token
        request = urllib.request.Request(config.callback_endpoint,
            data=json.dumps({'execution_id': contexts[0], 'tool': 'read_file', 'args': ['owner.txt']}).encode(),
            headers={'Authorization': authorization, 'Content-Type': 'application/json'})
        try:
            urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        else:
            raise AssertionError('Ended invocation callback context remained usable')
        factory._close_subagent_invocations()
        factory._cleanup_sandbox()
        try:
            urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        else:
            raise AssertionError('Closed callback capability remained usable')
        return {'owner_uid': coordinator.owner.pod_uid, 'pod_uid': connections[0].pod_uid,
                'twenty_acquisitions': 1, 'lost_create_response': lost.is_set(), 'kernels': observed_kernels,
                'execution_windows': windows, 'foreign_resource_rejected': True,
                'cancelled_child_preserved_parent': True,
                'script_matrix': scripts,
                'parent_kernel': parent_kernel, 'state_persisted': True, 'child_release_preserved_parent': True,
                'callback_statuses': callbacks[callback_start:], 'stale_context_rejected': True}
    finally:
        backend.api_factory = original_factory
        factory._close_subagent_invocations()
        factory._cleanup_sandbox()


@app.post('/__ksm/core')
async def controlled_core(request: Request):
    if request.client is None or request.client.host not in {'127.0.0.1', '::1'}:
        raise HTTPException(status_code=403, detail='Test fixture is loopback only')
    if get_coordinator() is None:
        raise HTTPException(status_code=503, detail='No test-owned Runtime')
    owned = {}
    execution = runtime_thread_manager.submit('agent-run',
        ManagedTaskSpec(task_name='fixture-core-agent', owner='ksm-test',
                        close_hook=lambda: owned['scope'].cancel() if 'scope' in owned else None), probe_core, owned)

    def finished(_):
        if 'lease' in owned:
            get_coordinator().finish(owned['lease'])

    execution.future.add_done_callback(finished)
    try:
        return await asyncio.wrap_future(execution.future)
    except asyncio.CancelledError:
        runtime_thread_manager.cancel(execution.execution_id, reason='Owned fixture request ended',
                                      wait_timeout=0, mark_stuck_on_timeout=False)
        raise


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=5014, log_level='warning')
