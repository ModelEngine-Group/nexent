# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Model execution reads remain private, read-only and tenant scoped."""

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import StorageScope

from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def models(tmp_path, monkeypatch):
    from infrastructure.rdb import model_invocation as module

    table = sa.Table('models', sa.MetaData(), sa.Column('model_id', sa.Integer, primary_key=True),
        sa.Column('tenant_id', sa.String), sa.Column('delete_flag', sa.String), sa.Column('model_name', sa.String),
        sa.Column('api_key', sa.String), sa.Column('http_headers', sa.JSON), sa.Column('input_modalities', sa.JSON),
        sa.Column('max_tokens', sa.Integer), sa.Column('ssl_verify', sa.Boolean), sa.Column('temperature', sa.Float),
        sa.Column('create_time', sa.DateTime), sa.Column('update_time', sa.DateTime))
    url = 'sqlite:///'+str(tmp_path/'models.db')
    engine = sa.create_engine(url)
    table.create(engine)
    with engine.begin() as connection:
        connection.execute(table.insert(), [{'model_id': key, 'tenant_id': tenant, 'delete_flag': deleted,
            'model_name': 'embed', 'api_key': 'private-key', 'http_headers': {'X-Private': 'token'},
            'input_modalities': ['text'], 'max_tokens': 2, 'ssl_verify': False, 'temperature': 0.2,
            'create_time': datetime(2026,11,18,1,2,3,tzinfo=timezone.utc), 'update_time': datetime(2026,11,18,1,2,4,tzinfo=timezone.utc)}
            for key, tenant, deleted in [(1,'tenant','N'),(2,'foreign','N'),(3,'tenant','Y')]])
    monkeypatch.setattr(module, 'models', table)
    monkeypatch.setattr(module, 'record_engine', lambda operation: sa.create_engine(url))
    yield module, engine
    engine.dispose()


def test_private_model_fields_preserve_types_but_cannot_escape_tenant(models):
    module, engine = models
    port = module.bind_invocation_models(StorageScope('runtime','tenant','operator',{module.DATASET}),engine)
    try:
        row = port.get(module.DATASET,1,context=context())
        assert row['http_headers']=={'X-Private':'token'} and row['input_modalities']==['text']
        assert row['api_key']=='private-key' and row['ssl_verify'] is False and row['max_tokens']==2
        assert row['temperature']==0.2
        assert port.get(module.DATASET,2,context=context()) is None
        assert port.get(module.DATASET,3,context=context()) is None
        with pytest.raises(ScopeDenied): port.create(module.DATASET,{'model_id':4},context=context())
    finally: port.close()


@pytest.mark.parametrize('role,system',[('management',False),('gateway',False),('runtime',True)])
def test_execution_port_rejects_foreign_roles_before_connection(role,system):
    from infrastructure.rdb import model_invocation as module

    engine = Mock()
    with pytest.raises(ScopeDenied):
        module.bind_invocation_models(StorageScope(role,None if system else 'tenant','operator',{module.DATASET},system=system),engine)
    engine.connect.assert_not_called()


def test_loader_accepts_actual_actor_and_preserves_timestamp_wire_format(models):
    from infrastructure.agentos_identity import ServicePrincipal

    module, _ = models
    actor = ServicePrincipal('operator','tenant')
    row = module.read_invocation_model(1, actor, context=context())
    assert row['update_time']=='2026-11-18T01:02:04'
    assert row['tenant_id']==actor.tenant_id
