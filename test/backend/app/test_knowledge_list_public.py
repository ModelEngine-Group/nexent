# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-LIST-03 keep public list selection and JSON on the async facade."""

from types import SimpleNamespace

import pytest
from contracts.errors.exceptions import TokenExpiredError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from management.api.knowledge_base import vectordatabase as module
from nexent.storage.errors import DeadlineExceeded, ScopeDenied

from backend.http.server.exception_handlers import register_exception_handlers


@pytest.fixture
def public(mocker):
    app=FastAPI();app.include_router(module.router);register_exception_handlers(app)
    def forbidden():raise AssertionError('Native VDB dependency used')
    app.dependency_overrides[module.get_vector_db_core]=forbidden
    mocker.patch.object(module,'get_current_user_id',return_value=('reader','tenant-a'))
    view=mocker.patch.object(module,'resolve_listing_view',return_value='resources')
    query=mocker.patch.object(module,'list_knowledge_indices',return_value={'indices':['kb'],'count':1,'index_permissions':{'kb':'EDIT'}})
    with TestClient(app) as client:yield SimpleNamespace(**locals())


def test_explicit_tenant_keeps_original_result_and_actual_identity(public):
    s=public;response=s.client.get('/indices',params={'tenant_id':'tenant-b','include_stats':True,'pattern':'kb*'})
    assert response.status_code==200 and response.json()==s.query.return_value
    call=s.query.await_args
    assert (call.args[0].user_id,call.args[0].tenant_id)==('reader','tenant-a') and call.args[1]=='tenant-b'
    assert call.kwargs['include_stats'] and call.kwargs['pattern']=='kb*'
    assert call.kwargs['context'].cancelled.is_set()


def test_default_tenant_merges_shared_with_one_budget(public):
    s=public;s.query.side_effect=[{'indices':['own'],'count':1},{'indices':['shared'],'count':1}]
    response=s.client.get('/indices')
    assert response.status_code==200 and response.json()=={'indices':['own','shared'],'count':2}
    calls=s.query.await_args_list
    assert calls[0].args[1]=='tenant-a' and calls[1].args[1]==module.ASSET_OWNER_TENANT_ID
    assert calls[0].kwargs['context'] is calls[1].kwargs['context']


def test_pagination_and_filters_keep_prefix_merge_contract(public):
    s=public;s.query.side_effect=[{'indices':['own'],'count':1,'total':1,'indices_info':[{'name':'own','knowledge_id':2,'update_time':'b'}]},
        {'indices':['shared'],'count':1,'total':1,'indices_info':[{'name':'shared','knowledge_id':1,'update_time':'a','permission':'EDIT'}]}]
    response=s.client.get('/indices',params={'offset':1,'limit':1,'keyword':'value','sources':'elasticsearch','models':'embed'})
    assert response.status_code==200 and response.json()['indices']==['shared']
    assert response.json()['indices_info'][0]['permission']=='READ_ONLY'
    assert all(c.kwargs['limit']==2 and c.kwargs['offset']==0 and c.kwargs['keyword']=='value'
               for c in s.query.await_args_list)


def test_inventory_uses_own_tenant_and_read_only_view(public):
    s=public;s.view.return_value='inventory'
    assert s.client.get('/indices').status_code==200
    assert s.query.await_args.args[1]=='tenant-a' and s.query.await_args.kwargs['inventory_read']


def test_asset_owner_default_does_not_merge_the_same_tenant_twice(public,mocker):
    s=public
    mocker.patch.object(module,'get_current_user_id',return_value=('publisher',module.ASSET_OWNER_TENANT_ID))
    assert s.client.get('/indices').json()==s.query.return_value
    assert s.query.await_count==1 and s.query.await_args.args[1]==module.ASSET_OWNER_TENANT_ID


def test_expired_identity_keeps_401_and_never_queries_resources(public,mocker):
    s=public
    mocker.patch.object(module,'get_current_user_id',side_effect=TokenExpiredError('expired'))
    response=s.client.get('/indices')
    assert response.status_code==401
    s.query.assert_not_awaited();s.view.assert_not_awaited()


@pytest.mark.parametrize('error,status,message', [(DeadlineExceeded(),504,'Knowledge base list timed out'),
    (ScopeDenied(),403,'No permission to list knowledge bases'),(ValueError('broken'),500,'Error get index: broken')])
def test_failures_keep_explicit_http_status_without_empty_success(public,error,status,message):
    s=public;s.query.side_effect=error
    response=s.client.get('/indices',params={'tenant_id':'tenant-a'})
    assert response.status_code==status and response.json()=={'message':message}
    assert s.query.await_count==1
