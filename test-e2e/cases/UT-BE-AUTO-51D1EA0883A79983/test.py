import logging

import pytest

import management.services.model.resolver as resolver
from consts.model import ModelConnectStatusEnum


class _FakeTenantConfigManager:
    def __init__(self):
        self.calls = []
        self.return_config = {}

    def get_model_config(self, key=None, default=None, tenant_id=None):
        self.calls.append({'key': key, 'default': default, 'tenant_id': tenant_id})
        return self.return_config


@pytest.mark.case_id('UT-BE-AUTO-51D1EA0883A79983')
@pytest.mark.stage('D1')
def test_shared_model_embedding_rerank_resolver(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    api_key_sentinel = 'sk-test-APIKEY-SECRET-987654'

    # resolve_model_record: tenant-scoped parameter passing and caching
    calls = []
    monkeypatch.setattr(
        resolver,
        'get_model_by_model_id',
        lambda *args: calls.append(args) or {'model_id': args[0]},
    )
    assert resolver.resolve_model_record(1, 'tenant-a') == {'model_id': 1}
    assert calls == [(1, 'tenant-a')]
    calls.clear()
    assert resolver.resolve_model_record(2, None) == {'model_id': 2}
    assert calls == [(2,)]

    calls.clear()
    cache = {}
    assert resolver.resolve_model_record(3, 'tenant-a', cache) == {'model_id': 3}
    assert calls == [(3, 'tenant-a')]
    calls.clear()
    assert resolver.resolve_model_record(3, 'tenant-a', cache) == {'model_id': 3}
    assert calls == []
    assert cache == {3: {'model_id': 3}}

    calls.clear()
    resolver.resolve_model_record(9, 'tenant-b')
    assert calls == [(9, 'tenant-b')]

    # is_model_available
    assert resolver.is_model_available({'connect_status': ModelConnectStatusEnum.AVAILABLE.value}) is True
    assert resolver.is_model_available(None) is False
    assert resolver.is_model_available({}) is False
    for status in ('detecting', 'unavailable', 'not_detected', '', None):
        assert resolver.is_model_available({'connect_status': status}) is False

    # get_model_descriptor
    descriptor_store = {
        (10, 't'): {'display_name': 'Multi', 'model_type': 'multi_embedding'},
        (11, 't'): {'display_name': 'LLM', 'model_type': 'llm'},
        (12, 't'): {'display_name': 'Emb', 'model_type': 'embedding'},
    }

    def fake_by_id(model_id, tenant_id=None):
        return descriptor_store.get((model_id, tenant_id))

    monkeypatch.setattr(resolver, 'get_model_by_model_id', fake_by_id)

    d_multi = resolver.get_model_descriptor(10, 't')
    assert (d_multi.display_name, d_multi.is_multimodal) == ('Multi', True)
    d_llm = resolver.get_model_descriptor(11, 't')
    assert (d_llm.display_name, d_llm.is_multimodal) == ('LLM', False)
    d_emb = resolver.get_model_descriptor(12, 't')
    assert (d_emb.display_name, d_emb.is_multimodal) == ('Emb', False)

    d_missing = resolver.get_model_descriptor(999, 't')
    assert (d_missing.display_name, d_missing.is_multimodal) == ('', False)
    d_none = resolver.get_model_descriptor(None, 't')
    assert (d_none.display_name, d_none.is_multimodal) == ('', False)

    def raising_by_id(model_id, tenant_id=None):
        raise RuntimeError('db down')

    monkeypatch.setattr(resolver, 'get_model_by_model_id', raising_by_id)
    d_err = resolver.get_model_descriptor(13, 't')
    assert (d_err.display_name, d_err.is_multimodal) == ('', False)

    # create_embedding_model and _build_model_config
    adapter_calls = []
    monkeypatch.setattr(
        resolver,
        'build_adapter_fresh',
        lambda cfg, modality, slot, tenant_id: adapter_calls.append(
            (cfg, modality, slot, tenant_id)
        ) or ('adapter', modality, slot),
    )

    adapter_calls.clear()
    assert resolver.create_embedding_model(
        {'model_name': 'e', 'model_type': 'embedding'}
    ) == ('adapter', 'embedding', 'embedding')
    assert adapter_calls[-1][1:] == ('embedding', 'embedding', None)

    adapter_calls.clear()
    resolver.create_embedding_model({'model_name': 'me', 'model_type': 'multi_embedding'})
    assert adapter_calls[-1][1] == 'multi_embedding'
    assert adapter_calls[-1][2] == 'multiEmbedding'

    adapter_calls.clear()
    resolver.create_embedding_model(
        {'model_name': 'f', 'model_type': 'embedding', 'model_factory': 'DashScope'}
    )
    assert adapter_calls[-1][0]['model_factory'] == 'DashScope'

    with pytest.raises(ValueError) as excinfo:
        resolver.create_embedding_model({'model_name': 'vlm-model', 'model_type': 'llm'})
    assert 'llm' in str(excinfo.value)
    assert 'vlm-model' in str(excinfo.value)

    assert resolver._build_model_config(
        {'model_name': 'b', 'model_factory': 'X'}
    )['model_factory'] == 'X'
    assert 'model_factory' not in resolver._build_model_config({'model_name': 'b2'})

    # get_embedding_model_by_id
    emb_store = {
        20: {'model_id': 20, 'model_type': 'embedding', 'model_name': 'emb20', 'api_key': api_key_sentinel},
        21: {'model_id': 21, 'model_type': 'multi_embedding', 'model_name': 'emb21'},
        22: {'model_id': 22, 'model_type': 'llm', 'model_name': 'llm22'},
        23: {'model_id': 23, 'model_type': 'rerank', 'model_name': 'rr23'},
    }

    def fake_emb_by_id(model_id, tenant_id=None):
        return emb_store.get(model_id)

    monkeypatch.setattr(resolver, 'get_model_by_model_id', fake_emb_by_id)

    adapter, model_id = resolver.get_embedding_model_by_id('t', 20)
    assert model_id == 20
    assert adapter == ('adapter', 'embedding', 'embedding')
    adapter, model_id = resolver.get_embedding_model_by_id('t', 21)
    assert model_id == 21
    assert adapter == ('adapter', 'multi_embedding', 'multiEmbedding')
    assert resolver.get_embedding_model_by_id('t', 22) == (None, None)
    assert resolver.get_embedding_model_by_id('t', 23) == (None, None)
    assert resolver.get_embedding_model_by_id('t', 999) == (None, None)

    # get_rerank_model
    rerank_records = {
        't': [
            {'model_repo': 'vendor', 'model_name': 'rr-1', 'model_type': 'rerank', 'model_id': 31},
            {'model_name': 'rr-2', 'model_type': 'rerank', 'model_id': 32},
        ],
    }

    def fake_get_model_records(filters, tenant_id):
        assert filters == {'model_type': 'rerank'}
        return rerank_records.get(tenant_id, [])

    monkeypatch.setattr(resolver, 'get_model_records', fake_get_model_records)
    fake_cm = _FakeTenantConfigManager()
    monkeypatch.setattr(resolver, 'tenant_config_manager', fake_cm)

    adapter_calls.clear()
    assert resolver.get_rerank_model('t', 'vendor/rr-1') == ('adapter', 'rerank', 'rerank')
    assert adapter_calls[-1][1:] == ('rerank', 'rerank', 't')
    assert adapter_calls[-1][0]['model_name'] == 'rr-1'
    assert adapter_calls[-1][0]['model_repo'] == 'vendor'

    adapter_calls.clear()
    assert resolver.get_rerank_model('t', 'rr-2') == ('adapter', 'rerank', 'rerank')
    assert adapter_calls[-1][0]['model_name'] == 'rr-2'
    assert adapter_calls[-1][1:] == ('rerank', 'rerank', 't')

    adapter_calls.clear()
    fake_cm.return_config = {'model_type': 'rerank', 'model_name': 'default-rr'}
    assert resolver.get_rerank_model('t', 'does-not-exist') == ('adapter', 'rerank', 'rerank')
    assert fake_cm.calls[-1] == {'key': 'RERANK_ID', 'default': None, 'tenant_id': 't'}
    assert adapter_calls[-1][0]['model_name'] == 'default-rr'
    assert adapter_calls[-1][1:] == ('rerank', 'rerank', 't')

    adapter_calls.clear()
    fake_cm.return_config = {'model_type': 'rerank', 'model_name': 'default-rr2'}
    assert resolver.get_rerank_model('t') == ('adapter', 'rerank', 'rerank')

    adapter_calls.clear()
    fake_cm.return_config = {'model_type': 'llm', 'model_name': 'llm-default'}
    assert resolver.get_rerank_model('t', 'nope') is None
    assert resolver.get_rerank_model('t') is None

    assert api_key_sentinel not in caplog.text
