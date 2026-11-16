# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Signed search HTTP, live Management grants and actual visible ES records."""

from contracts.agentos_knowledge import KnowledgeOperation, KnowledgeSearch
from contracts.errors.exceptions import RuntimeUpstreamError

from infrastructure.agentos_identity import ServicePrincipal, sign_call


def query(request, mode="semantic", rerank=False):
    return KnowledgeSearch(
        knowledge_ids=[1], file_ids=[request.file_id], query="worker", search_mode=mode,
        embedding_model=request.embedding_model,
        rerank_model={"model_id": 3, "revision": "v1"} if rerank else None,
    )


async def prove_search(rpc, actor, request, content, observed):
    for mode in ("accurate", "semantic", "hybrid"):
        result = await rpc.search_knowledge(query(request, mode, mode == "semantic"), actor.user_id, actor.tenant_id)
        assert len(result.hits) == 1
        hit = result.hits[0]
        assert hit.content == content and hit.file_id == request.file_id and hit.file_version == 0
        assert hit.filename == "source.txt"
        if mode == "semantic":
            assert hit.score_kind == "model.rerank" and hit.score == 0.98
        elif mode == "hybrid":
            assert hit.score_kind == "runtime.hybrid"
    assert observed == ["embedding", "rerank", "embedding"]
    for user, tenant in (("user-a", "tenant-b"), ("other", "tenant-a")):
        try:
            await rpc.search_knowledge(query(request), user, tenant)
            raise AssertionError("Unknown actor must not access indexed content")
        except RuntimeUpstreamError as error:
            assert error.status_code == 403
    body = query(request).model_dump_json().encode()
    token = sign_call(KnowledgeOperation.SEARCH, body, ServicePrincipal(actor.user_id, actor.tenant_id))
    async with rpc.create_client() as client:
        response = await client.post(rpc.runtime_url + "/api" + KnowledgeOperation.SEARCH.value,
                                     content=body + b" ", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 401
    assert observed == ["embedding", "rerank", "embedding"]
    return {"signed_search": True, "visible_rerank": True, "search_scope_denial": True}


async def prove_deleted_search(rpc, actor, request, observed):
    before = list(observed)
    result = await rpc.search_knowledge(query(request, "accurate"), actor.user_id, actor.tenant_id)
    assert result.hits == [] and observed == before
    return {"deleted_search_absent": True}
