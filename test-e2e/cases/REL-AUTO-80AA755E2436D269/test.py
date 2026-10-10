'''D5-SPECIAL: ES vector-store stats failure must fail-open for quota checks.

The durable source-file ledger is the sole quota metric; Elasticsearch physical
size is observability-only. ES adapter failures must never fail a personal or
tenant quota check or the usage display, while a source-ledger failure is the
only fail-closed path for strict quota checks.
'''

from __future__ import annotations

import logging

import pytest

from consts.error_code import ErrorCode
from consts.exceptions import AppException


TENANT_ID = 'tenant-d5-failopen'
USER_ID = 'user-d5-failopen'
KB_ID = 1001
INDEX_NAME = 'idx-d5-failopen'

MB = 1024 * 1024
GB = 1024 * 1024 * 1024

SOURCE_BYTES = 4 * MB
TENANT_SOURCE_BYTES = 5 * MB
USER_QUOTA_BYTES = 10 * MB
ES_STORE_SIZE_BYTES = int(1.5 * GB)


@pytest.mark.case_id('REL-AUTO-80AA755E2436D269')
@pytest.mark.stage('D5')
def test_es_stats_fail_open_source_ledger_quota(monkeypatch, caplog):
    import management.services.knowledge_base.service as kb_service
    import services.quota_service as quota_service
    from services.quota_service import QuotaService

    quota_service._usage_cache.clear()
    caplog.set_level(logging.WARNING)

    state = {'es_error': None, 'es_detail': None, 'ledger_error': None}

    config_values = {
        f'PERSONAL_KB_QUOTA_{USER_ID}': str(USER_QUOTA_BYTES),
        'KB_QUOTA_HARD_LIMIT_EDITABLE': 'true',
        'KB_QUOTA_WARNING_ENABLED': 'true',
        'KB_QUOTA_WARNING_THRESHOLD_PCT': '80',
        'KB_QUOTA_CRITICAL_THRESHOLD_PCT': '95',
    }

    def kb_list():
        return [{
            'knowledge_id': KB_ID,
            'index_name': INDEX_NAME,
            'knowledge_name': 'kb-d5-failopen',
            'knowledge_sources': 'elasticsearch',
            'quota_limit_bytes': None,
            'created_by': USER_ID,
        }]

    def single_config(tenant_id, key):
        if key not in config_values:
            return {}
        return {'config_value': config_values[key], 'tenant_config_id': 1}

    def committed_bytes_by_kb(tenant_id, knowledge_ids=None):
        if state['ledger_error'] is not None:
            raise state['ledger_error']
        return {KB_ID: SOURCE_BYTES}

    def tenant_committed(tenant_id):
        return TENANT_SOURCE_BYTES

    def get_vector_db_core():
        class _Core:
            def get_indices_detail(self, index_names):
                if state['es_error'] is not None:
                    raise state['es_error']
                return state['es_detail'] or {}

        return _Core()

    monkeypatch.setattr(quota_service, 'get_single_config_info', single_config)
    monkeypatch.setattr(quota_service, 'get_knowledge_info_by_tenant_id', lambda tenant_id, ordered=False: kb_list())
    monkeypatch.setattr(quota_service, 'get_private_knowledge_info_by_creator', lambda tenant_id, created_by: kb_list())
    monkeypatch.setattr(quota_service, 'get_private_knowledge_info_by_tenant_id', lambda tenant_id: kb_list())
    monkeypatch.setattr(quota_service, 'get_committed_bytes_by_kb', committed_bytes_by_kb)
    monkeypatch.setattr(quota_service, 'get_tenant_committed_source_bytes', tenant_committed)
    monkeypatch.setattr(kb_service, 'get_vector_db_core', get_vector_db_core)

    service = QuotaService(TENANT_ID, USER_ID)
    kb_record = kb_list()[0]

    state['es_detail'] = {
        INDEX_NAME: {'base_info': {'store_size': '1.5 GB', 'doc_count': 3, 'chunk_count': 9}}
    }
    usage = service.get_usage(force_refresh=True, detail=True)
    assert usage['total_bytes'] == TENANT_SOURCE_BYTES
    assert usage['es_physical_bytes'] == ES_STORE_SIZE_BYTES
    assert usage['es_physical_bytes'] > 0

    def run_es_fault_scenario(exc):
        caplog.clear()
        state['es_error'] = exc
        state['es_detail'] = None
        state['ledger_error'] = None

        service.check_personal_user_quota(USER_ID, 1 * MB)

        with pytest.raises(AppException) as over_user:
            service.check_personal_user_quota(USER_ID, 8 * MB)
        assert over_user.value.error_code == ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED
        assert '12.0 MB' in over_user.value.message

        service.check_personal_kb_quota(USER_ID, 1 * MB, kb_record)

        with pytest.raises(AppException) as over_kb:
            service.check_personal_kb_quota(USER_ID, 8 * MB, kb_record)
        assert over_kb.value.error_code == ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED

        usage = service.get_usage(force_refresh=True, detail=True)
        assert usage['total_bytes'] == TENANT_SOURCE_BYTES
        assert usage['es_physical_bytes'] == 0

        assert 'Failed to query ES index stats' in caplog.text
        lowered = caplog.text.lower()
        for marker in ('password', 'secret', 'api_key', 'apikey', 'access_key', 'bearer'):
            assert marker not in lowered

    run_es_fault_scenario(AppException(ErrorCode.SYSTEM_SERVICE_UNAVAILABLE, 'ES adapter reported failure'))
    run_es_fault_scenario(RuntimeError('ES connection refused'))

    caplog.clear()
    state['es_error'] = None
    state['es_detail'] = None
    state['ledger_error'] = RuntimeError('ledger db down')
    with pytest.raises(AppException) as ledger_failure:
        service.check_personal_user_quota(USER_ID, 1 * MB)
    assert ledger_failure.value.error_code == ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE
