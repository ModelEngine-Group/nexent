# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DOC-BATCH-01/02 preserve tenant-slot batching through read-only SI."""

from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from nexent.storage.errors import Conflict, InvalidInput, ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb import document_embedding_batch as module
from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def settings(tmp_path, monkeypatch):
    metadata = sa.MetaData()
    slots = sa.Table('slots', metadata,
        sa.Column('tenant_config_id', sa.Integer, primary_key=True), sa.Column('tenant_id', sa.String),
        sa.Column('config_key', sa.String), sa.Column('config_value', sa.String), sa.Column('delete_flag', sa.String))
    models = sa.Table('models', metadata,
        sa.Column('model_id', sa.Integer, primary_key=True), sa.Column('tenant_id', sa.String),
        sa.Column('chunk_batch', sa.Integer), sa.Column('delete_flag', sa.String), sa.Column('api_key', sa.String))
    url = 'sqlite:///' + str(tmp_path / 'batch.db')
    engine = sa.create_engine(url)
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(slots.insert(), [
            {'tenant_config_id': i, 'tenant_id': tenant, 'config_key': key, 'config_value': value, 'delete_flag': 'N'}
            for i, tenant, key, value in [(1, 'tenant', 'EMBEDDING_ID', '002'),
                (2, 'tenant', 'MULTI_EMBEDDING_ID', '3'), (3, ASSET_OWNER_TENANT_ID, 'EMBEDDING_ID', '4')]])
        connection.execute(models.insert(), [
            {'model_id': i, 'tenant_id': tenant, 'chunk_batch': batch, 'delete_flag': 'N', 'api_key': 'never-project'}
            for i, tenant, batch in [(2, 'tenant', 1), (3, 'tenant', 3), (4, ASSET_OWNER_TENANT_ID, 100)]])
    monkeypatch.setattr(module, 'slots', slots)
    monkeypatch.setattr(module, 'models', models)
    monkeypatch.setattr(module, 'record_engine', lambda operation: sa.create_engine(url))
    yield module, engine, slots, models
    engine.dispose()


@pytest.mark.parametrize('kind,tenant,expected', [
    ('embedding', 'tenant', 1), ('multi_embedding', 'tenant', 3), ('embedding', ASSET_OWNER_TENANT_ID, 64)])
def test_actual_slot_selection_retains_actor_and_resource_namespace(settings, kind, tenant, expected):
    assert module.read_document_embedding_batch(ServicePrincipal('operator', 'tenant'), tenant, kind,
                                                context=context()) == expected


@pytest.mark.parametrize('change', ['missing', 'invalid', 'deleted_slot', 'deleted_model', 'null', 'foreign_model'])
def test_original_missing_configuration_defaults_to_ten(settings, change):
    _, engine, slots, models = settings
    with engine.begin() as connection:
        if change == 'missing':
            connection.execute(slots.delete().where(slots.c.tenant_config_id == 1))
        elif change in {'invalid', 'deleted_slot'}:
            connection.execute(slots.update().where(slots.c.tenant_config_id == 1).values(
                **({'config_value': 'not-an-id'} if change == 'invalid' else {'delete_flag': 'Y'})))
        else:
            connection.execute(models.update().where(models.c.model_id == 2).values(
                **{'deleted_model': {'delete_flag': 'Y'}, 'null': {'chunk_batch': None},
                   'foreign_model': {'tenant_id': 'foreign'}}[change]))
    assert module.read_document_embedding_batch(ServicePrincipal('operator', 'tenant'), 'tenant', 'embedding',
                                                context=context()) == 10


def test_invalid_batch_and_ambiguous_slot_do_not_guess_or_rewrite(settings):
    _, engine, slots, models = settings
    actor = ServicePrincipal('operator', 'tenant')
    with engine.begin() as connection:
        connection.execute(models.update().where(models.c.model_id == 2).values(chunk_batch=0))
    with pytest.raises(InvalidInput):
        module.read_document_embedding_batch(actor, 'tenant', 'embedding', context=context())
    with engine.begin() as connection:
        connection.execute(slots.insert().values(tenant_config_id=5, tenant_id='tenant', config_key='EMBEDDING_ID',
                                                  config_value='3', delete_flag='N'))
    with pytest.raises(Conflict):
        module.read_document_embedding_batch(actor, 'tenant', 'embedding', context=context())


def test_projection_is_read_only_and_never_exposes_credentials(settings):
    _, engine, _, _ = settings
    port = module.bind_document_embedding_settings(StorageScope('runtime', 'tenant', 'operator', module.DATASETS), engine)
    try:
        assert port.scope.actor_id == 'operator'
        row = port.get(module.MODELS, 2, context=context())
        assert set(row) == {'model_id', 'tenant_id', 'chunk_batch', 'delete_flag'}
        assert port.get(module.MODELS, 4, context=context()) is None
        with pytest.raises(ScopeDenied):
            port.create(module.MODELS, {'model_id': 9}, context=context())
    finally:
        port.close()


@pytest.mark.parametrize('role,system', [('management', False), ('gateway', False), ('runtime', True)])
def test_foreign_role_or_system_scope_rejected_before_connect(role, system):
    engine = Mock()
    with pytest.raises(ScopeDenied):
        module.bind_document_embedding_settings(StorageScope(role, None if system else 'tenant', 'operator',
                                                             module.DATASETS, system=system), engine)
    engine.connect.assert_not_called()


def test_ungranted_tenant_and_invalid_modality_rejected_before_engine(monkeypatch):
    factory = Mock()
    monkeypatch.setattr(module, 'record_engine', factory)
    actor = ServicePrincipal('operator', 'tenant')
    with pytest.raises(ScopeDenied):
        module.read_document_embedding_batch(actor, 'foreign', 'embedding', context=context())
    with pytest.raises(InvalidInput):
        module.read_document_embedding_batch(actor, 'tenant', 'llm', context=context())
    factory.assert_not_called()
