from __future__ import annotations

import base64
import json
import os
import subprocess
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import urlsplit

import pytest

from shared.auth import TestIdentity
from shared.http import assert_status, client
from shared.factories.tags import register_tag_definition
from shared.factories.ownership import register_owned_http
from shared.asset_registry import AssetDependencyError


CASE_ID = 'API-AUTO-357B84F01BA6D321'
STAGE = 'D3'

LOCAL_PROVIDER = 'local'
AIDP_PROVIDER = 'aidp'
KNOWLEDGE_DOCUMENT_TYPE = 'knowledge_document'
KNOWLEDGE_CONTENT_BUCKET_KEY = 'knowledge_content'
PROJECTION_INDEX_NAME = 'nexent_tag_projection'


def _inspect_deployment(container):
    try:
        result = subprocess.run(
            ['docker', 'inspect', container], capture_output=True,
            text=True, timeout=15, check=False,
        )
        records = json.loads(result.stdout) if result.returncode == 0 else []
        if len(records) != 1:
            raise ValueError('container unavailable or ambiguous')
        return records[0]
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise AssetDependencyError(
            'services', 'elasticsearch', dependency_case_id='D0-ELASTICSEARCH',
            detail=f'cannot inspect {container}: {type(exc).__name__}',
        ) from exc


@contextmanager
def configured_product_elasticsearch():
    """Use the deployed ES from pytest's host without copying a key to disk."""
    from elasticsearch import Elasticsearch
    from consts import const as product_constants
    from management.services.knowledge_base import common

    host = os.environ.get('NEXENT_TEST_ELASTICSEARCH_URL', '').strip()
    if not host:
        container = os.environ.get('NEXENT_TEST_ELASTICSEARCH_CONTAINER', 'nexent-elasticsearch')
        ports = (_inspect_deployment(container).get('NetworkSettings') or {}).get('Ports') or {}
        published = ports.get('9200/tcp') or []
        choices = {int(item['HostPort']) for item in published
                   if str(item.get('HostPort', '')).isdigit()}
        if len(choices) != 1:
            raise AssetDependencyError(
                'services', 'elasticsearch', dependency_case_id='D0-ELASTICSEARCH',
                detail='set NEXENT_TEST_ELASTICSEARCH_URL: no unique host port',
            )
        host = f'http://127.0.0.1:{choices.pop()}'
    parsed = urlsplit(host)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        raise AssetDependencyError(
            'services', 'elasticsearch', dependency_case_id='D0-ELASTICSEARCH',
            detail='NEXENT_TEST_ELASTICSEARCH_URL must be an HTTP(S) URL',
        )
    api_key = os.environ.get('ELASTICSEARCH_API_KEY', '').strip()
    if not api_key:
        container = os.environ.get('NEXENT_TEST_CONFIG_CONTAINER', 'nexent-config')
        config = _inspect_deployment(container)
        values = dict(row.split('=', 1) for row in config.get('Config', {}).get('Env', [])
                      if '=' in row)
        api_key = values.get('ELASTICSEARCH_API_KEY', '')
    if not api_key:
        raise AssetDependencyError(
            'services', 'elasticsearch', dependency_case_id='D0-ELASTICSEARCH',
            detail='Elasticsearch API key is not configured',
        )
    try:
        healthy = Elasticsearch(host, api_key=api_key, request_timeout=10).ping()
    except Exception as exc:
        raise AssetDependencyError(
            'services', 'elasticsearch', dependency_case_id='D0-ELASTICSEARCH',
            detail=f'host-side Elasticsearch preflight failed: {type(exc).__name__}',
        ) from exc
    if not healthy:
        raise AssetDependencyError(
            'services', 'elasticsearch', dependency_case_id='D0-ELASTICSEARCH',
            detail='host-side Elasticsearch preflight returned unhealthy',
        )
    with (patch.object(product_constants, 'ES_HOST', host),
          patch.object(product_constants, 'ES_API_KEY', api_key),
          patch.object(common, 'ES_HOST', host),
          patch.object(common, 'ES_API_KEY', api_key)):
        yield


def encode_document_resource_id(provider, knowledge_base_id, provider_document_id):
    payload = json.dumps(
        [provider, knowledge_base_id, provider_document_id],
        ensure_ascii=False,
        separators=(',', ':'),
    ).encode('utf-8')
    return base64.urlsafe_b64encode(payload).decode('ascii')


class FailingProjectionCore:
    def create_index(self, index_name):
        return None

    def create_chunk(self, index_name, payload):
        raise RuntimeError('injected projection write failure')

    def delete_documents(self, index_name, resource_id):
        return None


def create_local_knowledge_base(identity):
    from database.knowledge_db import create_knowledge_record
    from management.services.knowledge_base.common import get_vector_db_core

    run_id = uuid.uuid4().hex
    record = create_knowledge_record({
        'knowledge_name': 'tag-projection-' + run_id,
        'knowledge_describe': 'auto-test document tag projection fixture',
        'user_id': identity.user_id,
        'tenant_id': identity.tenant_id,
    })
    index_name = record['index_name']
    try:
        register_owned_http(identity, 'owned_knowledge_bases', index_name,
                            f'/indices/{index_name}')
        provider_document_id = run_id + '.txt'
        core = get_vector_db_core()
        core.create_index(index_name)
        core.create_chunk(index_name, {
            'id': provider_document_id,
            'path_or_url': provider_document_id,
            'title': 'projection fixture document',
            'filename': provider_document_id,
            'content': 'document tag projection fixture content',
        })
    except BaseException:
        cleanup_knowledge_base(index_name)
        raise
    return index_name, provider_document_id


def query_projection_chunk(resource_id):
    from management.services.knowledge_base.common import get_vector_db_core

    core = get_vector_db_core()
    query = {'query': {'term': {'id': resource_id}}, 'size': 10}
    deadline = time.monotonic() + 10
    while True:
        result = core.search(index_name=PROJECTION_INDEX_NAME, query=query)
        hits = result.get('hits', {}).get('hits', [])
        if hits:
            return hits[0]['_source']
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.2)


def cleanup_knowledge_base(index_name):
    from database.knowledge_db import delete_knowledge_record
    from management.services.knowledge_base.common import get_vector_db_core

    try:
        get_vector_db_core().delete_index(index_name)
    except Exception:
        pass
    try:
        delete_knowledge_record({'index_name': index_name})
    except Exception:
        pass


@pytest.mark.stage(STAGE)
@pytest.mark.case_id(CASE_ID)
@pytest.mark.asyncio
async def test_document_tag_projection_state_machine(tenant_a_admin: TestIdentity):
    # The document adapter checks a real user-to-tenant KB permission. The
    # platform super-admin anchor has no such relationship in this deployment.
    identity = tenant_a_admin

    with configured_product_elasticsearch():
        await _exercise_document_tag_projection_state_machine(identity)


async def _exercise_document_tag_projection_state_machine(identity: TestIdentity):
    async with client('config', token=identity.access_token) as api:
        libraries_response = await api.get('/tag-libraries')
        assert_status(libraries_response, 200)
        libraries = libraries_response.json()
    content_library = next(
        item for item in libraries if item.get('bucket_key') == KNOWLEDGE_CONTENT_BUCKET_KEY
    )
    bucket_id = content_library['bucket_id']

    run_id = uuid.uuid4().hex
    async with client('config', token=identity.access_token) as api:
        definition_response = await api.post(
            '/tag-libraries/' + str(bucket_id) + '/definitions',
            json={
                'definition_name': 'doc-projection-' + run_id,
                'selection_mode': 'multi_select',
                'initial_values': ['value-a', 'value-b'],
            },
        )
        assert_status(definition_response, 200)
        definition = definition_response.json()
    register_tag_definition(identity, bucket_id, definition)
    definition_id = definition['definition_id']
    value_ids = [value['value_id'] for value in definition['values']]

    index_name, provider_document_id = create_local_knowledge_base(identity)
    encoded_resource_id = encode_document_resource_id(
        LOCAL_PROVIDER, index_name, provider_document_id
    )
    # The HTTP adapter accepts the provider's raw document ID. It encodes the
    # canonical resource ID internally for storage and projection lookup.
    assignment_url = (
        '/tag-libraries/assignments/' + KNOWLEDGE_DOCUMENT_TYPE + '/' + provider_document_id
    )
    query_params = {'provider': LOCAL_PROVIDER, 'knowledge_base_id': index_name}

    try:
        async with client('config', token=identity.access_token) as api:
            put_response = await api.put(
                assignment_url,
                params=query_params,
                json={'value_ids': value_ids},
            )
            assert_status(put_response, 200)
            assignment = put_response.json()
        assert assignment['assignment_count'] == len(value_ids)
        assert len(assignment['assignments']) == len(value_ids)

        async with client('config', token=identity.access_token) as api:
            status_response = await api.get(
                assignment_url + '/projection-status',
                params=query_params,
            )
            assert_status(status_response, 200)
            status = status_response.json()
        assert status['status'] == 'synced'
        assert status['version'] >= 1
        assert status['tag_count'] == len(value_ids)
        first_version = status['version']

        chunk = query_projection_chunk(encoded_resource_id)
        assert chunk is not None
        metadata = chunk['metadata']
        assert metadata['tenant_id'] == identity.tenant_id
        assert metadata['provider'] == LOCAL_PROVIDER
        assert metadata['knowledge_base_id'] == index_name
        assert metadata['provider_document_id'] == provider_document_id
        assert metadata['version'] == first_version
        assert len(metadata['tags']) == len(value_ids)

        async with client('config', token=identity.access_token) as api:
            put_again = await api.put(
                assignment_url,
                params=query_params,
                json={'value_ids': value_ids},
            )
            assert_status(put_again, 200)
        async with client('config', token=identity.access_token) as api:
            status_again = await api.get(
                assignment_url + '/projection-status',
                params=query_params,
            )
            assert_status(status_again, 200)
            idempotent_status = status_again.json()
        assert idempotent_status['status'] == 'synced'
        assert idempotent_status['version'] == first_version
        assert idempotent_status['retry_count'] == 0

        from services.tag_document_projection import project_document_assignments

        aidp_status = project_document_assignments(
            identity.tenant_id,
            AIDP_PROVIDER,
            index_name,
            provider_document_id,
            identity.user_id,
            enabled=True,
        )
        assert aidp_status['status'] == 'unsupported'
        assert aidp_status['last_error'] is not None
        assert aidp_status['next_attempt_at'] is None

        async with client('config', token=identity.access_token) as api:
            batch_response = await api.post(
                '/tag-libraries/documents/batch-status',
                params=query_params,
                json={
                    'document_ids': [provider_document_id],
                    'predicates': [
                        {'definition_id': definition_id, 'value_ids': value_ids}
                    ],
                },
            )
            assert_status(batch_response, 200)
            batch = batch_response.json()
        assert len(batch) == 1
        entry = batch[0]
        assert entry['document_id'] == provider_document_id
        assert entry['assignment_count'] == len(value_ids)
        assert entry['projection_status'] is not None
        assert entry['projection_status']['status'] == 'synced'

        from services.tag_management_service import TagManagementService

        matched = TagManagementService.filter_document_ids_by_predicates(
            identity.tenant_id,
            LOCAL_PROVIDER,
            index_name,
            [{'definition_id': definition_id, 'value_ids': value_ids}],
        )
        assert encoded_resource_id in matched
        aidp_matched = TagManagementService.filter_document_ids_by_predicates(
            identity.tenant_id,
            AIDP_PROVIDER,
            index_name,
            [{'definition_id': definition_id, 'value_ids': value_ids}],
        )
        assert aidp_matched == []

        from database.tag_management_db import TagManagementDB

        failed_document_id = uuid.uuid4().hex + '.txt'
        failed_resource_id = encode_document_resource_id(
            LOCAL_PROVIDER, index_name, failed_document_id
        )
        TagManagementDB.replace_resource_assignments(
            identity.tenant_id,
            KNOWLEDGE_DOCUMENT_TYPE,
            failed_resource_id,
            'knowledge_content',
            value_ids,
            identity.user_id,
        )
        failed_status = project_document_assignments(
            identity.tenant_id,
            LOCAL_PROVIDER,
            index_name,
            failed_document_id,
            identity.user_id,
            vdb_core=FailingProjectionCore(),
            enabled=True,
        )
        assert failed_status['status'] == 'failed'
        assert failed_status['retry_count'] == 1
        assert failed_status['last_error'] is not None
        assert failed_status['next_attempt_at'] is not None
        assert failed_status['last_attempt_at'] is not None
        expected_backoff = timedelta(seconds=30)
        observed_backoff = failed_status['next_attempt_at'] - failed_status['last_attempt_at']
        assert abs(observed_backoff.total_seconds() - expected_backoff.total_seconds()) < 5

        from database import document_tag_projection_db
        from services.tag_document_projection import retry_pending_document_projections

        state = document_tag_projection_db.get_projection_state(
            identity.tenant_id, LOCAL_PROVIDER, index_name, failed_document_id
        )
        assert state is not None
        assert state['status'] == 'failed'
        document_tag_projection_db.upsert_projection_state(
            tenant_id=identity.tenant_id,
            provider=LOCAL_PROVIDER,
            knowledge_base_id=index_name,
            provider_document_id=failed_document_id,
            resource_id=state['resource_id'],
            status='failed',
            version=state['version'],
            payload=state['payload'],
            retry_count=state['retry_count'],
            last_error=state['last_error'],
            last_attempt_at=state['last_attempt_at'],
            next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            actor_id=identity.user_id,
        )
        outcomes = retry_pending_document_projections(tenant_id=identity.tenant_id)
        assert outcomes['synced'] >= 1
        retried = document_tag_projection_db.get_projection_state(
            identity.tenant_id, LOCAL_PROVIDER, index_name, failed_document_id
        )
        assert retried['status'] == 'synced'
        assert retried['retry_count'] == 0
        assert retried['last_error'] is None
        assert retried['next_attempt_at'] is None

        from services.tag_document_projection import (
            clear_document_projection,
            clear_projection_states_for_knowledge_base,
            get_document_projection_status,
        )

        cleared = clear_document_projection(
            identity.tenant_id, LOCAL_PROVIDER, index_name, provider_document_id
        )
        assert cleared is True
        not_projected = get_document_projection_status(
            identity.tenant_id, LOCAL_PROVIDER, index_name, provider_document_id
        )
        assert not_projected['status'] == 'not_projected'
        assert not_projected['version'] == 0
        assert not_projected['tag_count'] == 0

        cleared_kb = clear_projection_states_for_knowledge_base(
            identity.tenant_id, LOCAL_PROVIDER, index_name
        )
        assert cleared_kb >= 1
        remaining = document_tag_projection_db.list_projection_states_for_knowledge_base(
            identity.tenant_id, LOCAL_PROVIDER, index_name
        )
        assert remaining == {}
    finally:
        # The synthetic AIDP unsupported branch is not owned by this local KB
        # provider, so clear that ledger entry explicitly. The product DELETE
        # path then cascades real local document tags and projection state.
        try:
            from services.tag_document_projection import clear_projection_states_for_knowledge_base
            clear_projection_states_for_knowledge_base(
                identity.tenant_id, AIDP_PROVIDER, index_name
            )
        finally:
            async with client('config', token=identity.access_token) as api:
                deleted = await api.delete(f'/indices/{index_name}')
                assert_status(deleted, (200, 204))
