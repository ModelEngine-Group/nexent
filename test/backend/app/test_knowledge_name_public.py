# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-KB-NAME-03 preserve the public name-check protocol without VDB."""

import logging
from types import SimpleNamespace

import pytest
from contracts.errors.exceptions import TokenExpiredError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from management.api.knowledge_base import vectordatabase as module
from nexent.storage.errors import DeadlineExceeded

from backend.http.server.exception_handlers import register_exception_handlers


@pytest.fixture
def public(mocker):
    app = FastAPI()
    app.include_router(module.router)
    register_exception_handlers(app)
    # The old endpoint injected this dependency even though it never used it.
    def forbidden():
        raise AssertionError('Name check must not initialize VDB')
    app.dependency_overrides[module.get_vector_db_core] = forbidden
    identity = mocker.patch.object(module, 'get_current_user_id', return_value=('operator', 'tenant-a'))
    lookup = mocker.patch.object(module, 'check_knowledge_name', return_value={'status': 'available'})
    with TestClient(app) as client:
        yield SimpleNamespace(**locals())


@pytest.mark.parametrize('status', ['available', 'exists_in_tenant'])
def test_original_path_shape_exact_name_and_actual_actor(public, status):
    s = public
    s.lookup.return_value = {'status': status}
    response = s.client.post('/indices/check_exist', json={'knowledge_name': ' KB '},
                             headers={'authorization': 'controlled-boundary'})
    assert response.status_code == 200 and response.json() == {'status': status}
    s.identity.assert_called_once_with('controlled-boundary')
    assert s.lookup.await_count == 1
    name, actor = s.lookup.await_args.args
    assert name == ' KB ' and (actor.user_id, actor.tenant_id) == ('operator', 'tenant-a')


@pytest.mark.parametrize('error,status,message', [
    (RuntimeError('read failed'), 500, 'Error checking existence for knowledge base: read failed'),
    (DeadlineExceeded(), 504, 'Knowledge base existence check timed out'),
    (TimeoutError(), 504, 'Knowledge base existence check timed out'),
])
def test_failure_never_claims_name_available(public, error, status, message, caplog):
    s = public
    s.lookup.side_effect = error
    response = s.client.post('/indices/check_exist', json={'knowledge_name': 'KB'})
    assert response.status_code == status and response.json() == {'message': message}
    assert s.lookup.await_count == 1
    if status == 504:
        assert not any(record.levelno == logging.ERROR for record in caplog.records)


def test_expired_identity_stops_before_query(public):
    s = public
    s.identity.side_effect = TokenExpiredError('expired')
    response = s.client.post('/indices/check_exist', json={'knowledge_name': 'KB'})
    assert response.status_code == 401
    s.lookup.assert_not_awaited()
