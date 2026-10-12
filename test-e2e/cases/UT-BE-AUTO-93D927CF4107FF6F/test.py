from __future__ import annotations

import logging
import re

import pytest

from management.services.agent import management as agent_management


CASE_ID = 'UT-BE-AUTO-93D927CF4107FF6F'
TENANT_ID = 'tenant_a'

_SECRET_PATTERNS = re.compile(r'(?i)(api[_-]?key|access[_-]?key|token|password|secret)')


def _patch_resolvers(monkeypatch, *, valid_ids=None, names_to_ids=None, quick_config=None):
    valid_ids = set(valid_ids or ())
    names_to_ids = dict(names_to_ids or {})
    calls = {'by_model_id': [], 'by_display_name': [], 'get_model_config': []}

    def _get_model_by_model_id(mid):
        calls['by_model_id'].append(mid)
        if mid in valid_ids:
            return {'model_id': mid, 'display_name': 'model-%d' % mid}
        return None

    def _get_model_id_by_display_name(display_name, tenant_id):
        calls['by_display_name'].append((display_name, tenant_id))
        return names_to_ids.get(display_name)

    class _TenantConfig:
        def get_model_config(self, key, tenant_id):
            calls['get_model_config'].append((key, tenant_id))
            return quick_config

    monkeypatch.setattr(agent_management, 'get_model_by_model_id', _get_model_by_model_id)
    monkeypatch.setattr(agent_management, 'get_model_id_by_display_name', _get_model_id_by_display_name)
    monkeypatch.setattr(agent_management, 'tenant_config_manager', _TenantConfig())
    return calls


def _assert_no_secrets(caplog):
    for record in caplog.records:
        msg = record.getMessage()
        assert not _SECRET_PATTERNS.search(msg), 'log leaks a secret marker: %r' % (msg,)


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D1')
def test_model_resolution_three_level_fallback(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger='management.services.agent.management')

    calls = _patch_resolvers(monkeypatch)
    assert agent_management._resolve_model_ids_with_fallback(None, None, 'Model', TENANT_ID) is None
    assert agent_management._resolve_model_ids_with_fallback([], [], 'Model', TENANT_ID) is None
    assert calls['by_model_id'] == []
    assert calls['by_display_name'] == []
    assert calls['get_model_config'] == []

    calls = _patch_resolvers(monkeypatch, valid_ids={101, 102, 103})
    assert agent_management._resolve_model_ids_with_fallback([101, 102, 101, 103], None, 'Model', TENANT_ID) == [101, 102, 103]
    assert calls['by_display_name'] == []
    assert calls['get_model_config'] == []

    calls = _patch_resolvers(monkeypatch, valid_ids={101, 102})
    assert agent_management._resolve_model_ids_with_fallback([101, 999, 102], None, 'Model', TENANT_ID) == [101, 102]
    assert calls['by_model_id'] == [101, 999, 102]
    assert calls['by_display_name'] == []
    assert calls['get_model_config'] == []

    calls = _patch_resolvers(monkeypatch, valid_ids={101}, names_to_ids={'Alpha': 201})
    assert agent_management._resolve_model_ids_with_fallback([101], ['Alpha'], 'Model', TENANT_ID) == [101]
    assert calls['by_display_name'] == []
    assert calls['get_model_config'] == []

    calls = _patch_resolvers(monkeypatch, names_to_ids={'Alpha': 201, 'Beta': 202})
    assert agent_management._resolve_model_ids_with_fallback([999], ['Alpha', 'Beta'], 'Model', TENANT_ID) == [201, 202]
    assert calls['by_display_name'] == [('Alpha', TENANT_ID), ('Beta', TENANT_ID)]
    assert calls['get_model_config'] == []

    calls = _patch_resolvers(monkeypatch, names_to_ids={'Alpha': 201})
    assert agent_management._resolve_model_ids_with_fallback(None, ['Alpha', 'Alpha'], 'Model', TENANT_ID) == [201]
    assert calls['by_display_name'] == [('Alpha', TENANT_ID), ('Alpha', TENANT_ID)]

    calls = _patch_resolvers(monkeypatch, quick_config={'model_id': 301, 'display_name': 'quick-config-llm'})
    assert agent_management._resolve_model_ids_with_fallback([999], ['Missing'], 'Model', TENANT_ID) == [301]
    assert calls['get_model_config'] == [('LLM_ID', TENANT_ID)]

    calls = _patch_resolvers(monkeypatch, quick_config=None)
    result = agent_management._resolve_model_ids_with_fallback([999], None, 'Business logic model', TENANT_ID)
    assert result == []
    assert (result[0] if result else None) is None
    assert calls['get_model_config'] == [('LLM_ID', TENANT_ID)]

    _assert_no_secrets(caplog)
