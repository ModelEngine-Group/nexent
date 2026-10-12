'''D2 contract test for POST /tasks chain enqueue.

Covers the endpoint contract introduced when create_task switched to calling
submit_process_forward_chain directly:

* success -> HTTP 201 with a non-empty chain task_id;
* enqueue failure (empty task_id) -> HTTP 503 with the fixed detail;
* request schema validation (source / source_type required).

Only submit_process_forward_chain (the contract boundary between the HTTP
layer and the Celery process->forward->cleanup chain) is stubbed so both the
201 and 503 branches are exercised deterministically.
'''

from __future__ import annotations

import pytest

CASE_ID = 'API-AUTO-EA69132B4642BB43'
ENQUEUE_DETAIL = 'Failed to enqueue data processing task'


def _valid_payload() -> dict:
    return {
        'source': 'contract-test://document.txt',
        'source_type': 'local',
        'chunking_strategy': 'basic',
        'index_name': 'contract_test_index',
        'original_filename': 'document.txt',
        'tenant_id': 'contract-test-tenant',
        'telemetry_context': {'case_id': CASE_ID},
    }


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D2')
def test_post_tasks_chain_enqueue_contract(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from consts import const

    # This route contract stubs enqueue; it must never require a live broker.
    # Patch canonical configuration before importing the Celery task package.
    monkeypatch.setattr(const, 'REDIS_URL', 'memory://')
    monkeypatch.setattr(const, 'REDIS_BACKEND_URL', 'cache+memory://')
    from apps.data_process_app import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    payload = _valid_payload()

    # Schema contract: source and source_type are required fields.
    missing_source = {k: v for k, v in payload.items() if k != 'source'}
    response = client.post('/tasks', json=missing_source)
    assert response.status_code == 422, response.text

    chain_id = '0f0e1a2b3c4d5e6f7a8b9c0d1e2f3a4b'

    # Success path: non-empty chain id -> HTTP 201 and non-empty task_id.
    monkeypatch.setattr(
        'apps.data_process_app.submit_process_forward_chain',
        lambda **kwargs: chain_id,
    )
    response = client.post('/tasks', json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body == {'task_id': chain_id}
    assert isinstance(body['task_id'], str) and body['task_id']

    # The chain submission receives the parameters from the request body.
    captured: dict = {}

    def recording_submit(**kwargs):
        captured.update(kwargs)
        return chain_id

    monkeypatch.setattr(
        'apps.data_process_app.submit_process_forward_chain',
        recording_submit,
    )
    response = client.post('/tasks', json=payload)
    assert response.status_code == 201, response.text
    assert captured['source'] == payload['source']
    assert captured['source_type'] == payload['source_type']
    assert captured['chunking_strategy'] == payload['chunking_strategy']
    assert captured['index_name'] == payload['index_name']
    assert captured['original_filename'] == payload['original_filename']
    assert captured['tenant_id'] == payload['tenant_id']

    # Failure path: empty task_id -> HTTP 503 with the fixed detail string,
    # and the response body does not leak internal stack traces or secrets.
    monkeypatch.setattr(
        'apps.data_process_app.submit_process_forward_chain',
        lambda **kwargs: '',
    )
    response = client.post('/tasks', json=payload)
    assert response.status_code == 503, response.text
    assert response.json() == {'detail': ENQUEUE_DETAIL}
    raw = response.text.lower()
    for secret_marker in ('api_key', 'password', 'secret', 'token', 'authorization'):
        assert secret_marker not in raw, raw
