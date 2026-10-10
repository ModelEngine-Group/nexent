"""Observe only owned runtime keys; never mutate Redis or global run state."""
from __future__ import annotations

import asyncio
import os

import redis

from shared.asset_registry import AssetDependencyError
from shared.case_evidence import write_case_evidence
from shared.deployment_guard import HTTP_SERVICES
from shared.factories.redis_target import _inspect, deployed_redis_urls


class StopObservation:
    def __init__(self, identity, case_id):
        self.identity, self.case_id = identity, case_id
        runtime_name = next(name for name, service in HTTP_SERVICES.items() if service == 'runtime')
        runtime = _inspect(runtime_name)
        config = _inspect(os.environ.get('NEXENT_TEST_CONFIG_CONTAINER', 'nexent-config'))
        runtime_env = dict(item.split('=', 1) for item in runtime['Config']['Env'] if '=' in item)
        config_env = dict(item.split('=', 1) for item in config['Config']['Env'] if '=' in item)
        runtime_url = runtime_env.get('RUNTIME_STATE_REDIS_URL') or runtime_env.get('REDIS_URL')
        if not runtime_url or runtime_url != config_env.get('REDIS_URL'):
            raise AssetDependencyError('services', 'runtime_state', detail=
                                       'Runtime state endpoint differs from the existing Redis resolver')
        general, _ = deployed_redis_urls()
        self.wire = redis.from_url(general, decode_responses=True,
                                   socket_timeout=5, socket_connect_timeout=5)
        self.records = []

    def read(self, target):
        suffix = f'{self.identity.user_id}:{target}'
        with self.wire.pipeline(transaction=True) as pipe:
            pipe.hget(f'runtime:run:{suffix}', 'status')
            pipe.hget(f'runtime:stream:done:{suffix}', 'status')
            pipe.xlen(f'runtime:stream:{suffix}')
            pipe.xrevrange(f'runtime:stream:{suffix}', count=1)
            status, stream_status, length, last = pipe.execute()
        return {'run_status': status, 'stream_status': stream_status,
                'stream_length': length, 'last_event_id': last[0][0] if last else None}

    def record(self, label, target, state):
        self.records.append({'phase': label, 'target': str(target), **state})
        write_case_evidence(self.case_id + '-stop', {'observations': self.records},
                            secrets=(self.identity.access_token, self.identity.refresh_token))

    async def wait_stopped(self, target):
        deadline = asyncio.get_running_loop().time() + 60
        while True:
            state = self.read(target)
            self.record('after_stop', target, state)
            if state['run_status'] == 'stopped':
                break
            assert asyncio.get_running_loop().time() < deadline, 'Owned runtime slot did not reach stopped within 60s'
            await asyncio.sleep(0.5)
        await asyncio.sleep(1)
        stable = self.read(target)
        self.record('stability', target, stable)
        assert stable == state, 'Owned stopped run continued emitting or changed its terminal state'
        return state

    def close(self):
        self.wire.close()


def assert_stop_ack(body):
    assert isinstance(body, dict) and body.get('status') == 'success', 'Stop was not acknowledged'
    assert isinstance(body.get('message'), str) and body['message'].strip(), 'Stop acknowledgment has no message'
    if 'already_stopped' in body:
        assert isinstance(body['already_stopped'], bool), 'Invalid optional already_stopped field'


def owned_history(body, target):
    data = body.get('data')
    rows = data if isinstance(data, list) else [data]
    assert len(rows) == 1 and isinstance(rows[0], dict), 'Owned history must contain exactly one conversation'
    assert str(rows[0].get('conversation_id')) == str(target), 'History returned another conversation'
    assert isinstance(rows[0].get('message'), list), 'History has no structured message list'
    return rows[0]


def conversation_total(body):
    data = body.get('data')
    assert isinstance(data, dict), 'Conversation page is not structured'
    metadata = data.get('metadata')
    assert isinstance(metadata, dict), 'Conversation page has no metadata'
    total = metadata.get('total')
    assert type(total) is int and total >= 0, 'Conversation count is missing or invalid'
    return total
