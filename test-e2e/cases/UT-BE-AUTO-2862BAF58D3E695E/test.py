import logging

import pytest

import services.runtime_state_service as rss
from services.runtime_state_service import RuntimeStateService


CASE_ID = 'UT-BE-AUTO-2862BAF58D3E695E'

UID = 'user-1'
CID = 42
CHUNK = 'hello-chunk'
STATUS = 'completed'
ERROR = None
AFTER_ID = '5-0'
LAST_ID = '0'
BLOCK_MS = 250
COUNT = 5
IDEM_KEY = 'idem-key'
TTL = 60
TENANT = 'tenant-a'
LIMIT = 100

TASK_NAMES = {
    'reset_stream_async': 'runtime-state-reset-stream',
    'get_run_state_async': 'runtime-state-get-run',
    'is_cancelled_async': 'runtime-state-is-cancelled',
    'append_stream_event_async': 'runtime-state-append-event',
    'mark_stream_completed_async': 'runtime-state-mark-stream-completed',
    'get_stream_status_async': 'runtime-state-get-stream-status',
    'read_stream_events_async': 'runtime-state-read-stream-events',
    'wait_for_stream_events_async': 'runtime-state-wait-stream-events',
    'acquire_idempotency_async': 'runtime-state-acquire-idempotency',
    'release_idempotency_async': 'runtime-state-release-idempotency',
    'consume_rate_limit_async': 'runtime-state-consume-rate-limit',
}

WRAPPERS = [
    ('reset_stream_async', 'reset_stream', (UID, CID), {}),
    ('get_run_state_async', 'get_run_state', (UID, CID), {}),
    ('is_cancelled_async', 'is_cancelled', (UID, CID), {}),
    ('append_stream_event_async', 'append_stream_event', (UID, CID, CHUNK), {}),
    ('mark_stream_completed_async', 'mark_stream_completed', (UID, CID, STATUS, ERROR), {}),
    ('get_stream_status_async', 'get_stream_status', (UID, CID), {}),
    ('read_stream_events_async', 'read_stream_events', (UID, CID, AFTER_ID), {}),
    ('wait_for_stream_events_async', 'wait_for_stream_events', (UID, CID, LAST_ID, BLOCK_MS, COUNT), {}),
    ('acquire_idempotency_async', 'acquire_idempotency', (IDEM_KEY, TTL), {}),
    ('release_idempotency_async', 'release_idempotency', (IDEM_KEY,), {}),
    ('consume_rate_limit_async', 'consume_rate_limit', (TENANT, LIMIT), {}),
]


class FakeThreadManager:
    def __init__(self, execute=False):
        self.calls = []
        self.results = {}
        self.execute = execute

    async def run(self, lane, spec, fn, *args, **kwargs):
        self.calls.append({'lane': lane, 'spec': spec, 'fn': fn, 'args': args, 'kwargs': kwargs})
        if self.execute:
            return fn(*args, **kwargs)
        return self.results.get(spec.task_name)


class FakePipeline:
    def __init__(self, client):
        self._client = client
        self._commands = []

    def incr(self, key):
        self._commands.append(('incr', key))
        return self

    def expire(self, key, ttl):
        self._commands.append(('expire', key, ttl))
        return self

    def execute(self):
        results = []
        for command in self._commands:
            if command[0] == 'incr':
                results.append(self._client.incr(command[1]))
            elif command[0] == 'expire':
                results.append(self._client.expire(command[1], command[2]))
        return results


class FakeRedisClient:
    def __init__(self):
        self.store = {}
        self.streams = {}
        self.calls = []
        self._fail = set()

    def reset(self):
        self.store.clear()
        self.streams.clear()
        self.calls.clear()
        self._fail.clear()

    def fail_on(self, method):
        self._fail.add(method)

    def clear_fail(self):
        self._fail.clear()

    def _record(self, method, args, kwargs):
        self.calls.append((method, args, kwargs))
        if method in self._fail:
            raise RuntimeError('fake redis failure: ' + method)

    def hset(self, key, mapping=None):
        self._record('hset', (key,), {'mapping': mapping})
        if key not in self.store:
            self.store[key] = {}
        self.store[key].update(mapping or {})
        return len(mapping or {})

    def hgetall(self, key):
        self._record('hgetall', (key,), {})
        return dict(self.store.get(key, {}))

    def get(self, key):
        self._record('get', (key,), {})
        return self.store.get(key)

    def set(self, key, value, nx=False, ex=None):
        self._record('set', (key, value), {'nx': nx, 'ex': ex})
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def setex(self, key, ttl, value):
        self._record('setex', (key, ttl, value), {})
        self.store[key] = value
        return True

    def incr(self, key):
        self._record('incr', (key,), {})
        value = int(self.store.get(key, 0)) + 1
        self.store[key] = str(value)
        return value

    def xadd(self, key, fields, maxlen=None, approximate=False):
        self._record('xadd', (key,), {'fields': fields, 'maxlen': maxlen, 'approximate': approximate})
        stream = self.streams.setdefault(key, [])
        event_id = str(len(stream) + 1) + '-0'
        stream.append((event_id, dict(fields)))
        return event_id

    def xrange(self, key, min='-', max='+', count=None):
        self._record('xrange', (key,), {'min': min, 'max': max, 'count': count})
        return list(self.streams.get(key, []))

    def xread(self, streams, count=None, block=None):
        self._record('xread', (streams,), {'count': count, 'block': block})
        result = []
        for stream_key, _last_id in streams.items():
            events = self.streams.get(stream_key, [])
            result.append([stream_key, list(events)])
        return result or None

    def delete(self, *keys):
        self._record('delete', keys, {})
        removed = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                removed += 1
            if key in self.streams:
                del self.streams[key]
                removed += 1
        return removed

    def expire(self, key, ttl):
        self._record('expire', (key, ttl), {})
        return True

    def pipeline(self):
        return FakePipeline(self)


class _FakeRedisModule:
    def __init__(self, client):
        self._client = client

    def from_url(self, *args, **kwargs):
        return self._client


@pytest.fixture
def fake_client():
    return FakeRedisClient()


@pytest.fixture
def fake_manager():
    return FakeThreadManager()


@pytest.fixture
def service(monkeypatch, fake_client):
    monkeypatch.setattr(rss, 'RUNTIME_STATE_REDIS_URL', 'redis://fake:6379/0')
    monkeypatch.setattr(rss, 'redis', _FakeRedisModule(fake_client))
    return RuntimeStateService()


@pytest.mark.case_id("UT-BE-AUTO-2862BAF58D3E695E")
@pytest.mark.stage('D1')
@pytest.mark.asyncio
async def _check_run_managed_routes_through_manager(service, fake_manager):
    service.set_thread_manager(fake_manager)
    for index, (async_name, _sync_name, _args, _kwargs) in enumerate(WRAPPERS):
        fake_manager.results[TASK_NAMES[async_name]] = 'managed-result-' + str(index)

    for async_name, sync_name, args, kwargs in WRAPPERS:
        task_name = TASK_NAMES[async_name]
        before = len(fake_manager.calls)
        result = await getattr(service, async_name)(*args, **kwargs)
        if async_name in {
            'reset_stream_async',
            'mark_stream_completed_async',
            'release_idempotency_async',
        }:
            assert result is None
        else:
            assert result == fake_manager.results[task_name]
        assert len(fake_manager.calls) == before + 1
        call = fake_manager.calls[-1]
        assert call['lane'] == 'control-io'
        assert call['spec'].task_name == task_name
        assert call['spec'].owner == 'services.runtime_state_service'
        assert call['fn'].__name__ == sync_name
        assert call['fn'].__self__ is service
        assert call['args'] == args
        assert call['kwargs'] == {}


@pytest.mark.stage('D1')
@pytest.mark.asyncio
async def _check_run_managed_fallback_calls_fn_directly(service):
    service._thread_manager = None
    captured = {}

    def direct_fn(*args, **kwargs):
        captured['args'] = args
        captured['kwargs'] = kwargs
        return 'direct-result'

    result = await service._run_managed('task-x', direct_fn, 1, 2, x=3)
    assert result == 'direct-result'
    assert captured == {'args': (1, 2), 'kwargs': {'x': 3}}


@pytest.mark.stage('D1')
@pytest.mark.asyncio
async def _check_async_wrappers_fallback_match_sync(service, fake_client):
    service._thread_manager = None
    for async_name, sync_name, args, kwargs in WRAPPERS:
        fake_client.reset()
        expected = getattr(service, sync_name)(*args, **kwargs)
        fake_client.reset()
        actual = await getattr(service, async_name)(*args, **kwargs)
        assert actual == expected


@pytest.mark.stage('D1')
@pytest.mark.asyncio
async def _check_managed_and_direct_paths_consistent(service, fake_client):
    manager = FakeThreadManager(execute=True)
    service.set_thread_manager(manager)

    service.mark_run_finished(UID, CID, 'stopped')
    direct_state = service.get_run_state(UID, CID)
    managed_state = await service.get_run_state_async(UID, CID)
    assert managed_state == direct_state
    assert direct_state['status'] == 'stopped'

    assert service.set_cancel_signal(UID, CID) is True
    assert service.is_cancelled(UID, CID) is True
    assert await service.is_cancelled_async(UID, CID) is True

    event_id = service.append_stream_event(UID, CID, 'chunk-a')
    direct_events = service.read_stream_events(UID, CID)
    managed_events = await service.read_stream_events_async(UID, CID)
    assert managed_events == direct_events
    assert direct_events == [(event_id, 'chunk-a')]


@pytest.mark.stage('D1')
def _check_register_run_contract(service, fake_client):
    service.register_run(UID, CID, message_id=7)
    hset_call = next(c for c in fake_client.calls if c[0] == 'hset')
    assert hset_call[1] == (service._run_key(UID, CID),)
    mapping = hset_call[2]['mapping']
    assert mapping['status'] == 'running'
    assert mapping['message_id'] == '7'
    assert mapping['owner_pod'] == service._pod_name
    assert 'started_at' in mapping
    assert 'updated_at' in mapping
    expire_call = next(c for c in fake_client.calls if c[0] == 'expire')
    assert expire_call[1] == (service._run_key(UID, CID), rss.RUNTIME_RUN_TTL_SECONDS)
    delete_call = next(c for c in fake_client.calls if c[0] == 'delete')
    assert delete_call[1] == (service._cancel_key(UID, CID),)


@pytest.mark.stage('D1')
def _check_set_cancel_signal_and_is_cancelled_contract(service, fake_client):
    assert service.set_cancel_signal(UID, CID) is True
    setex_call = next(c for c in fake_client.calls if c[0] == 'setex')
    assert setex_call[1] == (service._cancel_key(UID, CID), rss.RUNTIME_CANCEL_TTL_SECONDS, service._pod_name)
    assert service.is_cancelled(UID, CID) is True


@pytest.mark.stage('D1')
def _check_append_stream_event_contract(service, fake_client):
    event_id = service.append_stream_event(UID, CID, CHUNK)
    xadd_call = next(c for c in fake_client.calls if c[0] == 'xadd')
    assert xadd_call[1] == (service._stream_key(UID, CID),)
    assert xadd_call[2]['fields'] == {'chunk': CHUNK}
    assert xadd_call[2]['maxlen'] == rss.RUNTIME_STREAM_MAX_LEN
    assert xadd_call[2]['approximate'] is True
    expire_call = next(c for c in fake_client.calls if c[0] == 'expire')
    assert expire_call[1] == (service._stream_key(UID, CID), rss.RUNTIME_STREAM_TTL_SECONDS)
    assert event_id is not None


@pytest.mark.stage('D1')
def _check_read_stream_events_xrange_min_construction(service, fake_client):
    stream_key = service._stream_key(UID, CID)
    fake_client.streams[stream_key] = [('5-0', {'chunk': 'a'})]
    result = service.read_stream_events(UID, CID, after_id='4-0')
    xrange_call = next(c for c in fake_client.calls if c[0] == 'xrange')
    assert xrange_call[2]['min'] == '(4-0'
    assert result == [('5-0', 'a')]

    fake_client.calls.clear()
    result2 = service.read_stream_events(UID, CID)
    xrange_call2 = next(c for c in fake_client.calls if c[0] == 'xrange')
    assert xrange_call2[2]['min'] == '-'
    assert result2 == [('5-0', 'a')]


@pytest.mark.stage('D1')
def _check_wait_for_stream_events_contract(service, fake_client):
    stream_key = service._stream_key(UID, CID)
    fake_client.streams[stream_key] = [('1-0', {'chunk': 'a'})]
    result = service.wait_for_stream_events(UID, CID, '0', block_ms=250, count=5)
    xread_call = next(c for c in fake_client.calls if c[0] == 'xread')
    assert xread_call[1] == ({stream_key: '0'},)
    assert xread_call[2]['count'] == 5
    assert xread_call[2]['block'] == 250
    assert result == [('1-0', 'a')]


@pytest.mark.stage('D1')
def _check_mark_stream_completed_and_get_stream_status(service, fake_client):
    service.mark_stream_completed(UID, CID, 'completed', error='boom')
    status = service.get_stream_status(UID, CID)
    assert status['status'] == 'completed'
    assert status['error'] == 'boom'


@pytest.mark.stage('D1')
def _check_mark_run_finished_stop_resume_contract(service, fake_client):
    service.mark_run_finished(UID, CID, 'stopped')
    hset_call = next(c for c in fake_client.calls if c[0] == 'hset')
    assert hset_call[1] == (service._run_key(UID, CID),)
    assert hset_call[2]['mapping']['status'] == 'stopped'
    assert 'updated_at' in hset_call[2]['mapping']
    expire_keys = [c[1][0] for c in fake_client.calls if c[0] == 'expire']
    assert service._run_key(UID, CID) in expire_keys
    assert service._cancel_key(UID, CID) in expire_keys
    assert service._stream_key(UID, CID) in expire_keys
    assert service._stream_done_key(UID, CID) in expire_keys
    state = service.get_run_state(UID, CID)
    assert state['status'] == 'stopped'


@pytest.mark.stage('D1')
def _check_acquire_release_idempotency_contract(service, fake_client):
    assert service.acquire_idempotency(IDEM_KEY, TTL) is True
    set_call = next(c for c in fake_client.calls if c[0] == 'set')
    assert set_call[1] == (service._idempotency_key(IDEM_KEY), service._pod_name)
    assert set_call[2]['nx'] is True
    assert set_call[2]['ex'] == TTL
    service.release_idempotency(IDEM_KEY)
    delete_call = next(c for c in fake_client.calls if c[0] == 'delete')
    assert delete_call[1] == (service._idempotency_key(IDEM_KEY),)


@pytest.mark.stage('D1')
def _check_consume_rate_limit_contract(service, fake_client):
    count = service.consume_rate_limit(TENANT, LIMIT)
    assert count == 1


@pytest.mark.stage('D1')
def _check_sync_methods_return_safe_defaults_on_exception(service, fake_client):
    fake_client.fail_on('hgetall')
    assert service.get_run_state(UID, CID) == {}
    assert service.get_stream_status(UID, CID) == {}
    fake_client.clear_fail()

    fake_client.fail_on('setex')
    assert service.set_cancel_signal(UID, CID) is False
    fake_client.clear_fail()

    fake_client.fail_on('get')
    assert service.is_cancelled(UID, CID) is False
    fake_client.clear_fail()

    fake_client.fail_on('xadd')
    assert service.append_stream_event(UID, CID, CHUNK) is None
    fake_client.clear_fail()

    fake_client.fail_on('xrange')
    assert service.read_stream_events(UID, CID) == []
    fake_client.clear_fail()

    fake_client.fail_on('xread')
    assert service.wait_for_stream_events(UID, CID, LAST_ID) == []
    fake_client.clear_fail()

    fake_client.fail_on('delete')
    assert service.reset_stream(UID, CID) is None
    fake_client.clear_fail()

    fake_client.fail_on('hset')
    assert service.register_run(UID, CID) is None
    assert service.mark_run_finished(UID, CID, 'stopped') is None
    assert service.mark_stream_completed(UID, CID, 'completed') is None
    fake_client.clear_fail()


@pytest.mark.stage('D1')
def _check_client_raises_when_redis_url_missing(monkeypatch):
    monkeypatch.setattr(rss, 'RUNTIME_STATE_REDIS_URL', '')
    service = RuntimeStateService()
    with pytest.raises(ValueError):
        _ = service.client


@pytest.mark.stage('D1')
def _check_client_raises_when_redis_uninstalled(monkeypatch):
    monkeypatch.setattr(rss, 'RUNTIME_STATE_REDIS_URL', 'redis://fake:6379/0')
    monkeypatch.setattr(rss, 'redis', None)
    service = RuntimeStateService()
    with pytest.raises(ValueError):
        _ = service.client


@pytest.mark.stage('D1')
def _check_no_secrets_in_logs(caplog, service, fake_client):
    fake_client.fail_on('hgetall')
    with caplog.at_level(logging.WARNING, logger='services.runtime_state_service'):
        service.get_run_state(UID, CID)
    text = caplog.text.lower()
    assert text
    for secret in ('password', 'api_key', 'apikey', 'token', 'secret', 'sk-'):
        assert secret not in text


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D1')
@pytest.mark.asyncio
async def test_runtime_state_service_contract(
    service, fake_client, fake_manager, monkeypatch, caplog
):
    """Exercise every V5 step through one reportable case entry."""
    await _check_run_managed_routes_through_manager(service, fake_manager)
    await _check_run_managed_fallback_calls_fn_directly(service)
    fake_client.reset()
    await _check_async_wrappers_fallback_match_sync(service, fake_client)
    fake_client.reset()
    await _check_managed_and_direct_paths_consistent(service, fake_client)

    for check in (
        _check_register_run_contract,
        _check_set_cancel_signal_and_is_cancelled_contract,
        _check_append_stream_event_contract,
        _check_read_stream_events_xrange_min_construction,
        _check_wait_for_stream_events_contract,
        _check_mark_stream_completed_and_get_stream_status,
        _check_mark_run_finished_stop_resume_contract,
        _check_acquire_release_idempotency_contract,
        _check_consume_rate_limit_contract,
        _check_sync_methods_return_safe_defaults_on_exception,
    ):
        fake_client.reset()
        check(service, fake_client)

    fake_client.reset()
    _check_no_secrets_in_logs(caplog, service, fake_client)
    _check_client_raises_when_redis_url_missing(monkeypatch)
    _check_client_raises_when_redis_uninstalled(monkeypatch)
