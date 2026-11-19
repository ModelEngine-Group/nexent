# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-LIST-02 carry the old listing assertions over actual SI rows."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.errors.exceptions import RuntimeUpstreamError
from contracts.knowledge_collections import (
    KnowledgeCollectionDescription,
    KnowledgeCollectionMetrics,
    KnowledgeCollectionsDescribed,
    KnowledgeModelDisplay,
)
from management.services.knowledge_base.inventory import (
    knowledge_listing_operation,
    list_knowledge_indices,
)
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    set_default_thread_manager,
)
from nexent.storage.errors import Conflict, DeadlineExceeded, ScopeDenied

from infrastructure.knowledge_catalog import knowledge
from test.backend.services.test_knowledge_listing_storage import (
    storage as storage,  # noqa: PLC0414
)


@pytest.fixture
async def listing(storage):
    s = storage
    manager = ThreadManager(service_name='listing-unit', lane_policies={'control-io': LanePolicy('control-io', 1, 10)})
    manager.start(); set_default_thread_manager(manager)
    absent = set()
    async def describe(request, user, tenant):
        assert (user, tenant) == (s.actor.user_id, s.actor.tenant_id)
        return KnowledgeCollectionsDescribed(items=[KnowledgeCollectionDescription(knowledge_id=key,
            expected_revision=request.expected_revisions[key], present=key not in absent,
            metric='cosine' if key not in absent else None, dimensions=16 if key not in absent else None,
            statistics=KnowledgeCollectionMetrics(record_count=4,size_bytes=1024,created_at_ms=100,query_count=7,
                cache_hit_count=3,source_count=2,process_source='Clean',embedding_model_name='repo/embed')
                if request.include_statistics and key not in absent else None,
            model_display=KnowledgeModelDisplay(display_name='Displayed',is_multimodal=True)
                if request.include_statistics and key not in absent else None) for key in request.knowledge_ids])
    client = SimpleNamespace(describe_knowledge_collections=AsyncMock(side_effect=describe))
    try:
        yield SimpleNamespace(**locals())
    finally:
        assert not (await manager.shutdown(timeout=5)).stuck_execution_ids
        clear_default_thread_manager(manager)


async def invoke(s, **kwargs):
    return await list_knowledge_indices(s.s.actor,'tenant-a',reader=s.s.reader,client=s.client,**kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize('roles,expected', [(['USER'],{'kb-1':'CREATOR'}),
    (['DEV'],{'kb-1':'CREATOR','kb-3':'READ_ONLY'}), (['DEV','OPS'],{'kb-1':'CREATOR','kb-3':'READ_ONLY'}),
    (['ADMIN'],{'kb-1':'CREATOR','kb-3':'EDIT'}), (['SU'],{'kb-1':'CREATOR','kb-3':'EDIT'}),
    (['ASSET_OWNER'],{'kb-1':'CREATOR','kb-3':'EDIT'}), (['OPS'],{})])
async def test_role_union_creator_group_private_and_datamate_rules(listing, roles, expected):
    s=listing; s.s.roles[:]=roles
    result=await invoke(s)
    assert result=={'indices':list(expected),'count':len(expected),'index_permissions':expected}
    assert all(not c.args[0].include_statistics for c in s.client.describe_knowledge_collections.call_args_list)


@pytest.mark.asyncio
async def test_stats_preserve_full_contract_and_only_missing_names_are_backfilled(listing):
    s=listing
    result=await invoke(s,include_stats=True)
    info=result['indices_info'][0]
    assert set(info)=={'knowledge_id','tags','name','display_name','permission','group_ids','knowledge_sources',
        'ingroup_permission','is_multimodal','tenant_id','embedding_model_name','embedding_model_id','update_time',
        'summary_frequency','last_summary_time','preserve_source_file','stats'}
    assert info['name']=='kb-1' and info['display_name']=='Name 1' and info['permission']=='CREATOR'
    assert info['tags']==['Second','First'] and info['group_ids']==[9]
    assert info['embedding_model_name']=='Displayed' and info['is_multimodal'] and info['preserve_source_file'] is False
    assert info['stats']=={'base_info':{'doc_count':2,'chunk_count':4,'store_size':'1.00 KB','process_source':'Clean',
        'embedding_model':'repo/embed','embedding_dim':1024,'creation_date':100,'update_date':100},
        'search_performance':{'total_search_count':7,'hit_count':3}}
    with s.s.engine.connect() as conn:
        rows=conn.execute(sa.select(knowledge.c.embedding_model_name).where(knowledge.c.knowledge_id.in_([1,3]))).scalars().all()
    assert rows==['repo/embed','repo/embed']


@pytest.mark.asyncio
async def test_pagination_filters_and_facets_precede_stats_queries(listing):
    s=listing
    result=await invoke(s,include_stats=True,pagination_enabled=True,offset=0,limit=1,keyword='Name',sources=['elasticsearch'])
    assert result['indices']==['kb-3'] and result['total']==2 and result['next_offset']==1
    assert result['facets']=={'sources':['elasticsearch'],'models':[]}
    calls=s.client.describe_knowledge_collections.call_args_list
    assert calls[0].args[0].knowledge_ids==[3,1]
    assert calls[1].args[0].knowledge_ids==[3] and calls[1].args[0].include_statistics


@pytest.mark.asyncio
async def test_missing_physical_indices_and_patterns_do_not_delete_catalog(listing):
    s=listing; s.absent.add(3)
    result=await invoke(s,pattern='kb-*, -never'.replace(' ',''))
    assert result['indices']==['kb-1']
    with s.s.engine.connect() as conn:
        assert conn.execute(sa.select(knowledge.c.delete_flag).where(knowledge.c.knowledge_id==3)).scalar_one()=='N'


@pytest.mark.asyncio
async def test_optional_stat_error_is_visible_and_keeps_non_stat_fields(listing):
    s=listing; normal=s.client.describe_knowledge_collections.side_effect
    async def fail_stats(request,*args):
        response=await normal(request,*args)
        if request.include_statistics:
            response.items[0].statistics=None;response.items[0].statistics_error='unavailable'
        return response
    s.client.describe_knowledge_collections.side_effect=fail_stats
    result=await invoke(s,include_stats=True)
    assert result['indices_info'][0]['stats']=={'error':'unavailable'}
    assert result['indices_info'][0]['embedding_model_name']=='Displayed' and result['indices_info'][0]['group_ids']==[9]


@pytest.mark.asyncio
async def test_large_catalog_uses_si_pagination_and_agentos_batches(listing):
    s=listing
    with s.s.engine.begin() as conn:
        conn.execute(knowledge.insert(),[{'knowledge_id':key,'tenant_id':'tenant-a','index_name':f'kb-{key}',
            'knowledge_sources':'elasticsearch','created_by':'reader','ingroup_permission':'PRIVATE','delete_flag':'N','version':1}
            for key in range(10,515)])
    result=await invoke(s)
    assert result['count']==507
    assert [len(c.args[0].knowledge_ids) for c in s.client.describe_knowledge_collections.call_args_list]==[100]*5+[7]


@pytest.mark.asyncio
async def test_unknown_or_reordered_response_is_not_an_empty_catalog(listing):
    s=listing; normal=s.client.describe_knowledge_collections.side_effect
    async def reordered(request,*args):
        result=await normal(request,*args);result.items.reverse();return result
    s.client.describe_knowledge_collections.side_effect=reordered
    with pytest.raises(Conflict):await invoke(s)


@pytest.mark.asyncio
async def test_provider_denial_and_cancellation_do_not_retry_or_return_partial_lists(listing):
    s=listing;s.client.describe_knowledge_collections.side_effect=ScopeDenied()
    with pytest.raises(ScopeDenied):await invoke(s)
    assert s.client.describe_knowledge_collections.await_count==1
    s.client.describe_knowledge_collections.side_effect=asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):await invoke(s)


@pytest.mark.asyncio
async def test_inventory_does_not_backfill_and_all_permissions_are_read_only(listing):
    s=listing;s.s.roles[:]=['OPS']
    result=await invoke(s,include_stats=True,inventory_read=True)
    assert set(result['index_permissions'].values())=={'READ_ONLY'}
    assert all(c.args[0].view=='inventory' for c in s.client.describe_knowledge_collections.call_args_list)
    with s.s.engine.connect() as conn:
        assert all(value is None for value in conn.execute(sa.select(knowledge.c.embedding_model_name)).scalars())


@pytest.mark.asyncio
async def test_shared_rows_are_read_only_and_keep_actual_actor(listing):
    s=listing
    with s.s.engine.begin() as conn:
        conn.execute(knowledge.insert(),{'knowledge_id':7,'tenant_id':ASSET_OWNER_TENANT_ID,'index_name':'shared',
            'knowledge_sources':'elasticsearch','created_by':'publisher','ingroup_permission':'EDIT','delete_flag':'N','version':1})
    result=await list_knowledge_indices(s.s.actor,ASSET_OWNER_TENANT_ID,reader=s.s.reader,client=s.client)
    assert result['index_permissions']=={'shared':'READ_ONLY'}
    assert s.client.describe_knowledge_collections.await_args.args[2]=='tenant-a'


@pytest.mark.asyncio
@pytest.mark.parametrize('group_ids',[None,''])
async def test_both_empty_groups_preserve_read_only_access_and_default_display(listing,group_ids):
    from management.services.knowledge_base import inventory_records
    s=listing
    s.s.mocker.patch.object(inventory_records,'metadata_identity',return_value=({'tenant_id':'tenant-a'},('DEV',),[]))
    with s.s.engine.begin() as conn:
        conn.execute(knowledge.update().where(knowledge.c.knowledge_id==3).values(group_ids=group_ids))
    result=await invoke(s,include_stats=True)
    row=next(item for item in result['indices_info'] if item['name']=='kb-3')
    assert row['permission']=='READ_ONLY' and row['group_ids']==[9]


@pytest.mark.asyncio
@pytest.mark.parametrize('status,expected',[(403,ScopeDenied),(409,Conflict),(504,DeadlineExceeded)])
async def test_http_failure_is_mapped_without_a_retry_or_empty_list(listing,status,expected):
    s=listing
    s.client.describe_knowledge_collections.side_effect=RuntimeUpstreamError(status_code=status,content=b'{}',headers={})
    with pytest.raises(expected):await invoke(s)
    assert s.client.describe_knowledge_collections.await_count==1


@pytest.mark.asyncio
async def test_missing_statistics_receipt_is_not_silently_defaulted(listing):
    s=listing;normal=s.client.describe_knowledge_collections.side_effect
    async def missing(request,*args):
        response=await normal(request,*args)
        if request.include_statistics:response.items[0].statistics=None
        return response
    s.client.describe_knowledge_collections.side_effect=missing
    with pytest.raises(Conflict):await invoke(s,include_stats=True)


@pytest.mark.asyncio
async def test_shared_public_budget_logs_a_propagated_timeout_once(listing,caplog):
    s=listing
    s.client.describe_knowledge_collections.side_effect=RuntimeUpstreamError(status_code=504,content=b'{}',headers={})
    with pytest.raises(DeadlineExceeded):
        async with knowledge_listing_operation() as context:
            await list_knowledge_indices(s.s.actor,'tenant-a',reader=s.s.reader,client=s.client,context=context)
    assert sum('knowledge_list_timeout' in r.message for r in caplog.records)==1
