import asyncio
import builtins
import concurrent.futures
import contextlib
import logging
import threading
from unittest import mock

import pytest

from backend.adapters.jiuwen_sdk_adapter import run_async

CASE_ID = 'UT-BE-AUTO-4781AB28D8956C3F'


class FakeThreadManager:
    '''Minimal ThreadManager stand-in that records run_sync and executes fn.'''

    def __init__(self):
        self.calls = []

    def run_sync(self, lane, spec, fn, *args, timeout=None, **kwargs):
        self.calls.append({'lane': lane, 'spec': spec, 'fn': fn, 'args': args, 'kwargs': kwargs})
        future = concurrent.futures.Future()

        def _worker():
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as exc:
                future.set_exception(exc)

        thread = threading.Thread(target=_worker)
        thread.start()
        thread.join()
        return future.result(timeout=timeout)

    @property
    def last_call(self):
        return self.calls[-1]


def _running_loop():
    loop = mock.MagicMock(name='running_loop')
    loop.is_running.return_value = True
    return loop


def _nest_asyncio_import(available, module):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'nest_asyncio':
            if available:
                return module
            raise ImportError('nest_asyncio not available')
        return real_import(name, *args, **kwargs)

    return fake_import


@contextlib.contextmanager
def _managed_thread_fallback(loop, fake_manager, new_event_loop=None):
    patches = [
        mock.patch('asyncio.get_running_loop', return_value=loop),
        mock.patch('builtins.__import__', side_effect=_nest_asyncio_import(False, None)),
        mock.patch('nexent.core.concurrency.get_current_thread_manager', return_value=None),
        mock.patch(
            'nexent.core.agents.run_agent._get_default_agent_thread_manager',
            return_value=fake_manager,
        ),
    ]
    if new_event_loop is not None:
        patches.append(mock.patch('asyncio.new_event_loop', side_effect=new_event_loop))
    with contextlib.ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        yield


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D1')
def test_run_async_routes_coroutine_and_propagates_result_and_exception(caplog):
    async def direct():
        return 'direct-result'

    with mock.patch(
        'asyncio.get_running_loop', side_effect=RuntimeError('no running loop')
    ):
        assert run_async(direct()) == 'direct-result'

    async def nested():
        return 'nest-result'

    loop = _running_loop()
    loop.run_until_complete.return_value = 'nest-result'
    nest_module = mock.MagicMock(name='nest_asyncio')

    with mock.patch('asyncio.get_running_loop', return_value=loop), mock.patch(
        'builtins.__import__', side_effect=_nest_asyncio_import(True, nest_module)
    ):
        assert run_async(nested()) == 'nest-result'
    nest_module.apply.assert_called_once()
    loop.run_until_complete.assert_called_once()

    async def managed():
        return 'managed-result'

    fallback_loop = _running_loop()
    fake_manager = FakeThreadManager()
    created_loops = []

    class TrackingLoop(asyncio.AbstractEventLoop):
        # Inherit from AbstractEventLoop so asyncio.set_event_loop's
        # isinstance check accepts the tracking wrapper.
        def __init__(self, inner):
            self.inner = inner
            self.run_until_complete_calls = 0
            self.closed = False

        def run_until_complete(self, c):
            self.run_until_complete_calls += 1
            return self.inner.run_until_complete(c)

        def close(self):
            self.closed = True
            self.inner.close()

        def __getattr__(self, name):
            return getattr(self.inner, name)

    real_new_event_loop = asyncio.new_event_loop

    def tracked_new_event_loop():
        tracked = TrackingLoop(real_new_event_loop())
        created_loops.append(tracked)
        return tracked

    with _managed_thread_fallback(
        fallback_loop, fake_manager, new_event_loop=tracked_new_event_loop
    ), caplog.at_level(logging.INFO, logger='jiuwen_adapter'):
        assert run_async(managed()) == 'managed-result'

    call = fake_manager.last_call
    assert call['lane'] == 'model-tool-io'
    assert call['spec'].task_name == 'jiuwen-coroutine'
    assert call['spec'].owner == 'runtime'
    assert callable(call['fn'])
    assert len(created_loops) == 1
    assert created_loops[0].run_until_complete_calls == 1
    assert created_loops[0].closed is True

    class BoomError(Exception):
        pass

    async def failing():
        raise BoomError('boom')

    fake_manager2 = FakeThreadManager()
    with _managed_thread_fallback(_running_loop(), fake_manager2):
        with pytest.raises(BoomError, match='boom'):
            run_async(failing())
    assert fake_manager2.last_call['lane'] == 'model-tool-io'

    adapter_records = [r for r in caplog.records if r.name == 'jiuwen_adapter']
    for record in adapter_records:
        text = record.getMessage().lower()
        assert 'api_key' not in text
        assert 'password' not in text
        assert 'token' not in text
