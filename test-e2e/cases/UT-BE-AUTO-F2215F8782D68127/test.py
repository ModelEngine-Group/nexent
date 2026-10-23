from __future__ import annotations

import asyncio
import builtins
import concurrent.futures
import importlib
import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest
from shared.config import repo_root


CASE_ID = 'UT-BE-AUTO-F2215F8782D68127'


def _repo_root() -> Path:
    return repo_root()


def _stub_openjiuwen_if_missing() -> None:
    if 'adapters.jiuwen_sdk_adapter' in sys.modules:
        return
    try:
        if importlib.util.find_spec('openjiuwen') is not None:
            return
    except (ImportError, ValueError):
        pass
    base = types.ModuleType('openjiuwen.dev_tools.tune.base')
    base.Case = object
    base.EvaluatedCase = object
    for name in ('openjiuwen', 'openjiuwen.dev_tools', 'openjiuwen.dev_tools.tune'):
        mod = types.ModuleType(name)
        mod.__path__ = []
        mod.__package__ = name
        sys.modules[name] = mod
    sys.modules['openjiuwen.dev_tools.tune.base'] = base


def _load_adapter():
    _stub_openjiuwen_if_missing()
    import adapters.jiuwen_sdk_adapter as adapter
    return adapter


def _backend_py_files():
    backend = _repo_root() / 'backend'
    for path in backend.rglob('*.py'):
        rel = path.relative_to(backend)
        if any(part in {'__pycache__', '.venv', '.git'} for part in rel.parts):
            continue
        yield path


def _new_lane_policy(name='model-tool-io', workers=2, queue=4):
    from nexent.core.concurrency import LanePolicy
    return LanePolicy(
        name=name,
        max_workers=workers,
        max_queue_size=queue,
        queue_timeout_seconds=0,
        cancel_grace_seconds=5,
        shutdown_grace_seconds=15,
    )


def _new_manager():
    from nexent.core.concurrency import ThreadManager
    return ThreadManager(
        service_name='ut-be-auto-f2215f8782d68127',
        lane_policies={'model-tool-io': _new_lane_policy()},
    )


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D1')
def test_global_thread_pool_removal_and_run_async_migration(monkeypatch) -> None:
    # 1. deleted legacy module must be unresolvable
    assert importlib.util.find_spec('backend.utils.thread_utils') is None

    # 2. no residual GlobalThreadPool / thread_utils.submit reference
    for py_file in _backend_py_files():
        text = py_file.read_text(encoding='utf-8')
        for pattern in ('GlobalThreadPool', 'thread_utils.submit'):
            assert pattern not in text, f'{py_file} still references {pattern!r}'

    # 3. adapter imports cleanly and exposes run_async
    adapter = _load_adapter()
    assert callable(adapter.run_async)

    # 4. public concurrency API is exposed
    from nexent.core.concurrency import ManagedTaskSpec, ThreadManager, get_current_thread_manager
    assert callable(get_current_thread_manager)
    assert callable(ThreadManager)
    assert callable(ManagedTaskSpec)

    # 5. sync context (no running loop) -> asyncio.run branch
    async def no_loop_coro() -> str:
        return 'no-loop-result'

    assert adapter.run_async(no_loop_coro()) == 'no-loop-result'

    # 6. running loop + missing nest_asyncio -> ThreadManager.run_sync fallback
    class RecordingManager:
        def __init__(self):
            self.calls = []

        def run_sync(self, lane, spec, fn):
            # Mirror ThreadManager semantics: fn runs on a worker thread,
            # never on the thread that owns the running event loop.
            self.calls.append((lane, spec))
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(fn).result()

    recording = RecordingManager()
    monkeypatch.setattr('nexent.core.concurrency.get_current_thread_manager', lambda: None)
    monkeypatch.setattr(
        'nexent.core.agents.run_agent._get_default_agent_thread_manager',
        lambda: recording,
    )
    real_import = builtins.__import__

    def block_nest_asyncio(name, *args, **kwargs):
        if name == 'nest_asyncio':
            raise ImportError('nest_asyncio unavailable for fallback branch coverage')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', block_nest_asyncio)

    async def fallback_coro() -> int:
        return 42

    # run_async must be invoked inside a running loop to reach the
    # nest_asyncio-less ThreadManager fallback branch.
    async def _invoke_fallback() -> int:
        return adapter.run_async(fallback_coro())

    assert asyncio.run(_invoke_fallback()) == 42
    assert len(recording.calls) == 1
    lane, spec = recording.calls[0]
    assert lane == 'model-tool-io'
    assert spec.task_name == 'jiuwen-coroutine'
    assert spec.owner == 'runtime'

    # 7. manager start -> run_sync -> shutdown lifecycle closes cleanly
    from nexent.core.concurrency import ManagerState
    manager = _new_manager()
    assert manager.state is ManagerState.CREATED
    manager.start()
    assert manager.state is ManagerState.RUNNING

    observed = []
    result = manager.run_sync(
        'model-tool-io',
        ManagedTaskSpec(task_name='closure-task', owner='runtime'),
        lambda: observed.append('ran') or 'closure-ok',
    )
    assert result == 'closure-ok'
    assert observed == ['ran']
    assert manager.snapshot().active_count == 0
    asyncio.run(manager.shutdown(timeout=15))
    assert manager.state is ManagerState.CLOSED
    assert manager.snapshot().active_count == 0

    # 8a. unknown lane raises KeyError, not a fake success
    unknown = _new_manager()
    unknown.start()
    with pytest.raises(KeyError):
        unknown.submit('no-such-lane', ManagedTaskSpec(task_name='x', owner='y'), lambda: None)
    asyncio.run(unknown.shutdown(timeout=15))
    assert unknown.state is ManagerState.CLOSED

    # 8b. submit before start raises ThreadManagerNotRunning
    from nexent.core.concurrency import ThreadManagerNotRunning
    not_started = _new_manager()
    with pytest.raises(ThreadManagerNotRunning):
        not_started.submit('model-tool-io', ManagedTaskSpec(task_name='x', owner='y'), lambda: None)

    # 9. no plaintext secret field is logged by the adapter source
    secret_fields = ('api_key', 'access_key', 'access_token', 'password', 'secret')
    adapter_path = _repo_root() / 'backend' / 'adapters' / 'jiuwen_sdk_adapter.py'
    for lineno, line in enumerate(adapter_path.read_text(encoding='utf-8').splitlines(), 1):
        if not any(token in line for token in ('logger', 'logging', '_logger')):
            continue
        lowered = line.lower()
        for field in secret_fields:
            assert field not in lowered, (
                f'plaintext secret {field!r} in log line {adapter_path}:{lineno}: {line.strip()}'
            )
