# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-SHARED-SEARCH-03/04 reads real journals in distinct own/asset scopes."""

from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.agentos import ModelMetadata
from contracts.agentos_knowledge import (
    KnowledgeBaseGrant,
    KnowledgeSample,
    KnowledgeSearch,
    KnowledgeSearchGrant,
)
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.knowledge_chunk_mutation import ChunkMutationIntent
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import (
    Page,
    SearchHit,
    StorageScope,
    VectorKey,
    VectorRecord,
    WriteOutcome,
)
from runtime.knowledge_base.chunk_admission import ChunkMutationAdmission
from runtime.knowledge_base.sample import KnowledgeSampleService
from runtime.knowledge_base.search import KnowledgeSearchService

from infrastructure.rdb.knowledge_jobs import FILES, JOBS
from infrastructure.rdb.knowledge_lifecycle import bind_knowledge_lifecycle
from test.backend.services.test_knowledge_chunk_creation import context
from test.backend.services.test_knowledge_chunk_creation import (
    creation as creation,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_chunk_creation import (
    lifecycle as lifecycle,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_chunk_creation import (
    sqlite_threads as sqlite_threads,  # noqa: PLC0414
)


@pytest.fixture
async def mixed(creation):
    s = creation
    actor = s.s.actor
    scope = StorageScope("runtime", ASSET_OWNER_TENANT_ID, actor.user_id, {FILES, JOBS})
    asset_mutations = bind_knowledge_lifecycle(scope, s.s.engine, mode="mutation")
    asset_reads = bind_knowledge_lifecycle(scope, s.s.engine, mode="read", knowledge_ids=(2,))
    records = {1: s.s.record, 2: asset_reads}
    grants = {k: KnowledgeBaseGrant(knowledge_id=k, collection="collection" if k==1 else "shared",
        resource_tenant_id=actor.tenant_id if k==1 else ASSET_OWNER_TENANT_ID, embedding_model_id=2,
        revision="a"*64) for k in (1,2)}
    vectors = {}
    try:
        for k, mutations in ((1,s.s.mutation_records),(2,asset_mutations)):
            resource = grants[k]
            def seed(mutations=mutations, k=k, resource=resource):
                journal = ChunkMutationAdmission(mutations,k)
                request = ChunkMutationIntent(knowledge_id=k,chunk_id=f"manual-{k}",request_key="seed",operation="create",
                    resource_revision=resource.revision,changes={"content":"body"})
                value,_=journal.reserve(request,context=context())
                journal.begin(value["mutation_id"],context=context())
                return journal.complete(value["mutation_id"],count_delta=1,outcome=WriteOutcome.CONFIRMED,context=context())
            receipt = await s.db(seed)
            from nexent.storage.models import Revision
            row = VectorRecord(VectorKey(resource.collection,f"manual-{k}"),(1.,0.,0.),{
                "knowledge_id":k,"file_id":None,"file_version":None,"chunk_index":None,"content":"body",
                "filename":None,"location":{},"embedding_model_id":2,"embedding_revision":"r1"},Revision(receipt["mutation_id"]))
            port = Mock(scope=StorageScope("runtime",resource.resource_tenant_id,actor.user_id,{resource.collection}))
            port.describe_collection.return_value = SimpleNamespace(dimensions=3)
            port.search.return_value = (SearchHit(row.key,.8,"cosine",row.payload,row.generation),)
            port.scan.return_value = Page((row,))
            vectors[resource.collection]=port
        calls=[]
        async def authorize(request,user,tenant):
            assert (user,tenant)==(actor.user_id,actor.tenant_id)
            calls.append((user,tenant))
            return KnowledgeSearchGrant(knowledge_bases=[grants[k] for k in request.knowledge_ids])
        client = SimpleNamespace(authorize_knowledge_search=authorize)
        s.models.get=AsyncMock(return_value=ModelMetadata(model_id=2,model_type="embedding",display_name=None,revision="r1"))

        @contextmanager
        def ports(principal,grant,dimensions,*,context):
            assert principal==actor
            yield ({r.knowledge_id:records[r.knowledge_id] for r in grant.knowledge_bases},
                   {r.collection:vectors[r.collection] for r in grant.knowledge_bases})

        service=KnowledgeSearchService(client,s.models,ports=ports)
        sample=KnowledgeSampleService(client,s.models,ports=ports)
        request=KnowledgeSearch(knowledge_ids=[1,2],query="body",embedding_model={"model_id":2,"revision":"r1"})
        yield SimpleNamespace(**locals())
    finally:
        asset_reads.close()
        asset_mutations.close()


async def test_same_request_reads_own_and_asset_journals_without_changing_actor(mixed):
    s=mixed
    result=await s.service.search(s.request,s.actor)
    assert {hit.knowledge_id for hit in result.hits}=={1,2}
    assert s.s.models.invoke.await_args.args[1]==s.actor
    assert s.calls==[(s.actor.user_id,s.actor.tenant_id)]*2


async def test_shared_sample_uses_resource_record_scope_and_actor_model_scope(mixed):
    s=mixed
    result=await s.sample.sample(KnowledgeSample(knowledge_id=2,expected_revision="a"*64),s.actor)
    assert result.documents[0].file_ref is None and result.documents[0].chunks[0].embedding==[1.,0.,0.]
    s.s.models.get.assert_awaited_once_with(2,s.actor)
    s.s.models.invoke.assert_not_awaited()


@pytest.mark.parametrize("fault",["record-tenant","vector-actor","foreign-grant"])
async def test_scope_mismatch_is_rejected_before_vector_queries(mixed,fault):
    s=mixed
    if fault=="record-tenant":s.records[2]=s.records[1]
    elif fault=="vector-actor":s.vectors["shared"].scope=replace(s.vectors["shared"].scope,actor_id="foreign")
    else:s.grants[2]=s.grants[2].model_copy(update={"resource_tenant_id":"foreign"})
    with pytest.raises(ScopeDenied):
        await s.service.search(s.request,s.actor)
    for port in s.vectors.values():port.search.assert_not_called()
    if fault=="foreign-grant":s.s.models.invoke.assert_not_awaited()


async def test_resource_namespace_revocation_never_returns_prior_results(mixed):
    s=mixed
    original=s.s.models.invoke.return_value
    async def revoke(*args):
        s.grants[2]=s.grants[2].model_copy(update={"resource_tenant_id":"foreign"})
        return original
    s.s.models.invoke.side_effect=revoke
    with pytest.raises(ScopeDenied):
        await s.service.search(s.request,s.actor)
