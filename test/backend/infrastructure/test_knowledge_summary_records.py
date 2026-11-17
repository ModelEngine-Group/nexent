# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Automatic summary composition restricts discovery and model configuration reads."""

from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from contracts.knowledge_summary import (
    SUMMARY_DATASET,
    SUMMARY_DISPATCH_DATASET,
    SUMMARY_MODEL_DATASET,
)
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import PageRequest, RecordQuery, StorageScope

from infrastructure.rdb import knowledge_summary as mapping
from infrastructure.rdb import knowledge_summary_dispatch as dispatch
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_summary_schedule import (
    isolated_connections,  # noqa: F401
)
from test.backend.services.test_knowledge_summary_schedule import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_summary_schedule import (
    setup as setup,  # noqa: PLC0414
)


def test_discovery_reads_only_attested_identity_and_cannot_write(setup, monkeypatch):
    journal, _, update, engine, table = setup
    monkeypatch.setattr(dispatch, 'knowledge', table)
    port = dispatch.bind_summary_dispatch(engine)
    try:
        update('cleanse_knowledge', summary_frequency='3h')
        assert port.query(SUMMARY_DISPATCH_DATASET, RecordQuery(), PageRequest(), context=context()).items == ()
        journal.configure('kb-one', '3h', context=context())
        row = port.query(SUMMARY_DISPATCH_DATASET, RecordQuery(), PageRequest(), context=context()).items[0]
        assert row['user_id'] == 'user-a' and row['tenant_id'] == 'tenant-a'
        assert set(row) == {'knowledge_id','tenant_id','index_name','user_id','delete_flag'}
        with pytest.raises(ScopeDenied):
            port.create(SUMMARY_DISPATCH_DATASET, row, context=context())
        with pytest.raises(ScopeDenied):
            port.query(SUMMARY_DATASET, RecordQuery(), PageRequest(), context=context())
    finally:port.close()


def test_default_model_projection_excludes_foreign_tenant_and_credentials(setup, monkeypatch):
    engine = setup[3]
    table = sa.Table('summary_config_fixture', sa.MetaData(), sa.Column('tenant_config_id',sa.Integer,primary_key=True),
        sa.Column('tenant_id',sa.String),sa.Column('config_key',sa.String),sa.Column('config_value',sa.String),sa.Column('delete_flag',sa.String))
    table.create(engine)
    monkeypatch.setattr(mapping,'TenantConfig',SimpleNamespace(__table__=table))
    with engine.begin() as connection:
        connection.execute(table.insert(),[{'tenant_config_id':i,'tenant_id':t,'config_key':k,'config_value':v,'delete_flag':'N'}
            for i,t,k,v in [(1,'tenant-a','LLM_ID','5'),(2,'tenant-b','LLM_ID','6'),(3,'tenant-a','API_KEY','never-exposed')]])
    port = mapping.bind_summary_records(StorageScope('management','tenant-a','user-a',{SUMMARY_MODEL_DATASET}),engine)
    try:
        values = port.query(SUMMARY_MODEL_DATASET,RecordQuery(),PageRequest(),context=context()).items
        assert len(values) == 1 and values[0]['config_value'] == '5'
        assert 'config_key' not in values[0]
        with pytest.raises(ScopeDenied):port.create(SUMMARY_MODEL_DATASET,values[0],context=context())
    finally:port.close()
