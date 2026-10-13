'''D2 contract test for F-131 process health endpoints (/health/live, /health/ready).'''

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.app_factory import create_app


class _ManagerState:
    '''Contract-boundary stand-in for the thread manager state value.'''

    def __init__(self, value: str) -> None:
        self.value = value


class _ManagerSnapshot:
    '''Contract-boundary stand-in for the result of manager.snapshot().'''

    def __init__(self, state_value: str, stuck_count: int) -> None:
        self.state = _ManagerState(state_value)
        self.stuck_count = stuck_count


class _ThreadManagerStub:
    '''Thread manager double exposing the snapshot() surface the health contract reads.'''

    def __init__(self, state_value: str, stuck_count: int = 0) -> None:
        self._state_value = state_value
        self._stuck_count = stuck_count

    def snapshot(self) -> _ManagerSnapshot:
        return _ManagerSnapshot(self._state_value, self._stuck_count)


_SECRET_MARKERS = ('api_key', 'apikey', 'password', 'token', 'secret')


def _assert_no_plaintext_secrets(bodies: list[dict]) -> None:
    composite = repr(bodies).lower()
    for marker in _SECRET_MARKERS:
        assert marker not in composite, f'response leaked sensitive marker {marker!r}'


@pytest.mark.stage('D2')
@pytest.mark.case_id('API-AUTO-CD0683F112D04918')
def test_health_live_and_ready_contract() -> None:
    app = create_app(title='Health Contract Test', enable_monitoring=False)
    route_paths = {getattr(route, 'path', None) for route in app.routes}
    assert '/health/live' in route_paths
    assert '/health/ready' in route_paths

    bodies: list[dict] = []

    with TestClient(app) as client:
        live = client.get('/health/live')
        assert live.status_code == 200, live.text
        assert live.json() == {'status': 'alive'}
        bodies.append(live.json())

    app.state.thread_manager = _ThreadManagerStub('running', 0)
    with TestClient(app) as client:
        ready = client.get('/health/ready')
        assert ready.status_code == 200, ready.text
        assert ready.json() == {
            'status': 'ready',
            'manager_state': 'running',
            'stuck_count': 0,
        }
        bodies.append(ready.json())

    app.state.thread_manager = _ThreadManagerStub('stopping', 0)
    with TestClient(app) as client:
        ready = client.get('/health/ready')
        assert ready.status_code == 503, ready.text
        assert ready.json() == {
            'status': 'not_ready',
            'manager_state': 'stopping',
            'stuck_count': 0,
        }
        bodies.append(ready.json())

    app.state.thread_manager = _ThreadManagerStub('running', 5)
    with TestClient(app) as client:
        ready = client.get('/health/ready')
        assert ready.status_code == 503, ready.text
        assert ready.json() == {
            'status': 'not_ready',
            'manager_state': 'running',
            'stuck_count': 5,
        }
        bodies.append(ready.json())

    app.state.thread_manager = None
    with TestClient(app) as client:
        ready = client.get('/health/ready')
        assert ready.status_code == 200, ready.text
        assert ready.json() == {'status': 'ready'}
        bodies.append(ready.json())

    runtime_app = create_app(title='Nexent Runtime API', enable_monitoring=False)
    config_app = create_app(title='Nexent Config API', enable_monitoring=False)
    runtime_app.state.thread_manager = _ThreadManagerStub('running', 0)
    config_app.state.thread_manager = _ThreadManagerStub('stopping', 0)
    with TestClient(runtime_app) as runtime_client, TestClient(config_app) as config_client:
        runtime_ready = runtime_client.get('/health/ready')
        config_ready = config_client.get('/health/ready')
        assert runtime_ready.status_code == 200, runtime_ready.text
        assert runtime_ready.json()['manager_state'] == 'running'
        bodies.append(runtime_ready.json())
        assert config_ready.status_code == 503, config_ready.text
        assert config_ready.json()['manager_state'] == 'stopping'
        bodies.append(config_ready.json())

    _assert_no_plaintext_secrets(bodies)
