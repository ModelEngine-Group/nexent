import json
import logging
from unittest.mock import Mock

import pytest

from services.redis_service import RedisService


CASE_ID = 'UT-BE-AUTO-BB2EEA5C837979B4'


class _FakeClient:
    def __init__(self):
        self.store = {}
        self.set_calls = []
        self.setex_calls = []

    def set(self, key, value):
        self.set_calls.append((key, value))
        self.store[key] = value
        return True

    def setex(self, key, ttl, value):
        self.setex_calls.append((key, ttl, value))
        self.store[key] = value
        return True

    def exists(self, key):
        return 1 if key in self.store else 0

    def delete(self, *keys):
        deleted = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                deleted += 1
        return deleted


def _service_with(client):
    service = RedisService()
    service._client = client
    return service


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D1')
def test_document_delete_fence_tri_state_and_redis_unavailable_fallback(caplog):
    assert RedisService._document_fence_key('doc-1') == 'kb:delete:fence:file:doc-1'
    assert RedisService._document_fence_key(None) is None
    assert RedisService._document_fence_key('') is None

    client = Mock()
    service = _service_with(client)
    assert service.mark_document_delete_requested(file_id='doc-1', requested_by='user-1') is True
    client.set.assert_called_once()
    client.setex.assert_not_called()
    key, payload_str = client.set.call_args.args
    assert key == 'kb:delete:fence:file:doc-1'
    payload = json.loads(payload_str)
    assert payload['file_id'] == 'doc-1'
    assert payload['requested_by'] == 'user-1'
    assert isinstance(payload['requested_at'], float)

    client = Mock()
    service = _service_with(client)
    assert service.mark_document_delete_requested(file_id=None) is False
    assert service.mark_document_delete_requested(file_id='') is False
    client.set.assert_not_called()
    client.set.side_effect = RuntimeError('redis down')
    assert service.mark_document_delete_requested(file_id='doc-1', requested_by='user-1') is False

    client = Mock()
    client.exists.return_value = 1
    service = _service_with(client)
    assert service.is_document_delete_requested(file_id='doc-1') is True
    client.exists.return_value = 0
    assert service.is_document_delete_requested(file_id='doc-1') is False

    empty_client = Mock()
    service = _service_with(empty_client)
    assert service.is_document_delete_requested(file_id=None) is False
    assert service.is_document_delete_requested(file_id='') is False
    empty_client.exists.assert_not_called()

    client = Mock()
    client.exists.side_effect = RuntimeError('redis down')
    service = _service_with(client)
    with pytest.raises(RuntimeError):
        service.is_document_delete_requested(file_id='doc-1')

    client = Mock()
    client.delete.return_value = 1
    service = _service_with(client)
    assert service.clear_document_delete_fence(file_id='doc-1') == 1
    client.delete.return_value = 0
    assert service.clear_document_delete_fence(file_id='doc-1') == 0

    empty_client = Mock()
    service = _service_with(empty_client)
    assert service.clear_document_delete_fence(file_id=None) == 0
    assert service.clear_document_delete_fence(file_id='') == 0
    empty_client.delete.assert_not_called()

    client = Mock()
    client.delete.side_effect = RuntimeError('redis down')
    service = _service_with(client)
    assert service.clear_document_delete_fence(file_id='doc-1') == 0

    fake = _FakeClient()
    service = _service_with(fake)
    assert service.mark_document_delete_requested(file_id='doc-1', requested_by='user-1') is True
    assert service.is_document_delete_requested(file_id='doc-1') is True
    assert service.clear_document_delete_fence(file_id='doc-1') == 1
    assert service.is_document_delete_requested(file_id='doc-1') is False

    with caplog.at_level(logging.INFO, logger='services.redis_service'):
        service.mark_document_delete_requested(file_id='doc-1', requested_by='user-1')
        service.clear_document_delete_fence(file_id='doc-1')
    for record in caplog.records:
        if record.name != 'services.redis_service':
            continue
        message = record.getMessage().lower()
        for secret in ('api_key', 'apikey', 'password', 'token', 'secret'):
            assert secret not in message
