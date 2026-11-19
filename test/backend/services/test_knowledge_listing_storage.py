# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-LIST-SI-01 prove scoped catalog, display tags and cache writes."""

from contextlib import contextmanager
from datetime import datetime
from time import monotonic
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from management.services.knowledge_base import inventory_records as module
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import OperationContext

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.knowledge_catalog import knowledge
from infrastructure.knowledge_listing import (
    bind_listing_records,
    tag_assignments,
    tag_values,
)
from infrastructure.rdb.tenant_config_record import TenantConfig


@pytest.fixture
def storage(mocker):
    engine = sa.create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=sa.pool.StaticPool,
                              execution_options={'schema_translate_map': {'nexent': None}})
    for table in (knowledge, tag_assignments, tag_values, TenantConfig.__table__):
        table.create(engine)
    actor = ServicePrincipal('reader', 'tenant-a')
    roles = ['DEV']
    @contextmanager
    def identities(*args, **kwargs):
        yield None, None, None
    mocker.patch.object(module, 'metadata_identity', side_effect=lambda *a, **kw: ({'tenant_id': 'tenant-a'}, tuple(roles), [5]))
    opened = []
    @contextmanager
    def ports(principal, tenant, *, context):
        assert principal == actor
        records = bind_listing_records(principal, tenant, engine)
        opened.append(records)
        try:
            yield records
        finally:
            records.close()
    with engine.begin() as conn:
        for key, tenant, owner, permission, deleted, source in [(1,'tenant-a','reader','PRIVATE','N','elasticsearch'),
            (2,'tenant-a','other','PRIVATE','N','elasticsearch'), (3,'tenant-a','other','READ_ONLY','N','elasticsearch'),
            (4,'tenant-b','other','EDIT','N','elasticsearch'), (5,'tenant-a','reader','EDIT','Y','elasticsearch'),
            (6,'tenant-a','reader','EDIT','N','datamate')]:
            conn.execute(knowledge.insert(), {'knowledge_id':key,'tenant_id':tenant,'index_name':f'kb-{key}',
                'knowledge_name':f'Name {key}','knowledge_sources':source,'created_by':owner,'updated_by':owner,
                'ingroup_permission':permission,'group_ids':'5' if key==3 else None,'delete_flag':deleted,'version':1,
                'embedding_model_name':None,'update_time':datetime(2026,1,key),'preserve_source_file':False})  # noqa: DTZ001 - Legacy timestamps are naive.
        conn.execute(TenantConfig.__table__.insert(), {'tenant_config_id':1,'tenant_id':'tenant-a',
            'config_key':'DEFAULT_GROUP_ID','config_value':'9','delete_flag':'N'})
        conn.execute(tag_values.insert(), [{'value_id':1,'tenant_id':'tenant-a','definition_id':1,'display_value':'First','delete_flag':'Y'},
            {'value_id':2,'tenant_id':'tenant-a','definition_id':1,'display_value':'Second','delete_flag':'N'}])
        for key, value, deleted in [(1,2,'N'),(2,1,'N'),(3,2,'N'),(4,1,'Y')]:
            conn.execute(tag_assignments.insert(), {'assignment_id':key,'tenant_id':'tenant-a','definition_id':1,
                'value_id':value,'resource_type':'knowledge_base','resource_id':'kb-1','delete_flag':deleted})
    reader = module.KnowledgeListingReader(ports=ports, identities=identities)
    yield SimpleNamespace(**locals())
    engine.dispose()


def context():
    return OperationContext('listing-storage', monotonic()+10)


def test_catalog_dac_sorting_default_groups_and_original_timestamp_format(storage):
    s = storage
    rows = s.reader.snapshot(s.actor, 'tenant-a', view='resources', ordered=True, context=context())
    assert [r['knowledge_id'] for r in rows] == [3,1]
    assert rows[0]['permission']=='READ_ONLY' and rows[0]['group_ids']==[5]
    assert rows[1]['permission']=='CREATOR' and rows[1]['group_ids']==[9]
    assert rows[1]['update_time']=='2026-01-01T00:00:00Z'


def test_tags_preserve_join_order_dedup_and_legacy_deleted_value_semantics(storage):
    s = storage
    rows = s.reader.tags(s.actor, 'tenant-a', [{'index_name':'kb-1'}], context=context())
    assert rows[0]['tags']==['Second','First']


def test_missing_name_backfill_is_scoped_and_audited_once(storage):
    s = storage
    row = s.reader.snapshot(s.actor, 'tenant-a', view='resources', ordered=False, context=context())[0]
    s.reader.backfill(s.actor, row, 'repo/embed', context=context())
    with s.engine.connect() as conn:
        saved = conn.execute(sa.select(knowledge).where(knowledge.c.knowledge_id==row['knowledge_id'])).mappings().one()
    assert saved['embedding_model_name']=='repo/embed' and saved['updated_by']=='reader' and saved['version']==2
    s.reader.backfill(s.actor, row, 'must-not-overwrite', context=context())
    with s.engine.connect() as conn:
        assert conn.execute(sa.select(knowledge.c.embedding_model_name).where(knowledge.c.knowledge_id==row['knowledge_id'])).scalar_one()=='repo/embed'


def test_foreign_tenant_requires_live_su_without_changing_actor(storage):
    s = storage
    with pytest.raises(ScopeDenied):
        s.reader.snapshot(s.actor,'tenant-b',view='resources',ordered=False,context=context())
    s.roles[:]=['SU']
    rows = s.reader.snapshot(s.actor,'tenant-b',view='resources',ordered=False,context=context())
    assert [r['knowledge_id'] for r in rows]==[4] and s.opened[-1].scope.actor_id=='reader'
