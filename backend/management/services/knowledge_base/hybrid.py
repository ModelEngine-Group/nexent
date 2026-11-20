# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public hybrid search with Runtime-owned query embedding."""

import asyncio
import json
from threading import Event
from time import monotonic, perf_counter
from types import SimpleNamespace
from uuid import uuid4

from contracts.agentos_knowledge import KnowledgeContentRequest
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeUpstreamError
from management.clients.model import embed_query
from management.services.knowledge_base.common import KnowledgeBaseNeedsModelConfigError
from management.services.knowledge_base.file_reader import KnowledgeFileReader
from management.services.knowledge_base.image_ticket import issue_image_url
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded, ScopeDenied
from nexent.storage.models import OperationContext

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient


def project_retrieved_image(hit, actor, *, northbound=False):
    if hit.image_ref is None:
        if hit.public_document is None:
            raise ScopeDenied()
        return dict(hit.public_document)
    request = KnowledgeContentRequest(
        knowledge_id=hit.knowledge_id, file_id=hit.file_id, file_version=hit.file_version,
        image_ref=hit.image_ref,
    )
    url = issue_image_url(request, actor, northbound=northbound)
    position = {key: hit.location[key] for key in ("page_number", "sheet_name", "coordinates") if key in hit.location}
    metadata = {"process_source": "UniversalImageExtractor", "image_url": url}
    if "chunk_index" in hit.location:
        metadata["chunk_index"] = hit.location["chunk_index"]
    return {
        "id": hit.chunk_id,
        "filename": hit.filename,
        "process_source": "UniversalImageExtractor",
        "metadata": metadata,
        "content": json.dumps({"source_file": hit.filename, "position": position, "image_url": url}, ensure_ascii=False),
    }


async def _resolve_model(client, index, model_id, actor):
    model = None
    if model_id:
        try:
            model = await client.get_model(model_id, user_id=actor.user_id, tenant_id=actor.tenant_id)
        except RuntimeUpstreamError as error:
            if error.status_code != 404:
                raise
    if model is None or model.model_id != model_id or model.model_type not in {"embedding", "multi_embedding"}:
        raise KnowledgeBaseNeedsModelConfigError(
            index_name=index,
            message=f"Knowledge base '{index}' does not have an embedding model configured. Please select a model in the knowledge base settings.",
        )
    return model


async def search_public_hybrid(
    index_names, query, actor, *, top_k, weight_accurate, vdb_core, reader=None, client=None,
):
    if not query or not query.strip():
        raise ValueError("Query text is required for hybrid search")
    if not index_names:
        raise ValueError("At least one index name is required")
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0")
    if weight_accurate is not None and not 0 <= weight_accurate <= 1:
        raise ValueError("weight_accurate must be between 0 and 1")
    if weight_accurate is None:
        weight_accurate = 0.7 if any(char.isdigit() for char in query) else 0.5

    reader = reader or KnowledgeFileReader()
    client = client or AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)
    stop = Event()
    context = OperationContext("hybrid-search-" + uuid4().hex, monotonic() + 180, cancelled=stop)
    first_index = index_names[0]
    try:
        async with asyncio.timeout(context.remaining()):
            try:
                resource = await run_blocking(
                    "public-hybrid-resource", reader.knowledge, first_index, actor,
                    context=context, lane="control-io", owner=__name__,
                )
            except ValueError as error:
                raise ValueError(
                    f"No embedding model found for index '{first_index}'. Please configure an embedding model for this knowledge base."
                ) from error
            model = await _resolve_model(client, first_index, resource["embedding_model_id"], actor)
            started = perf_counter()
            vector = await embed_query(
                model_id=model.model_id, query=query, user_id=actor.user_id,
                tenant_id=actor.tenant_id, revision=model.revision, client=client,
            )
            raw = await run_blocking(
                "public-hybrid-search", vdb_core.hybrid_search,
                index_names=index_names, query_text=query, query_embedding=vector, top_k=top_k,
                weight_accurate=weight_accurate,
                embedding_model=SimpleNamespace(
                    model_type="multimodal" if model.model_type == "multi_embedding" else "embedding"
                ),
                lane="control-io", owner=__name__,
            )
            elapsed_ms = int((perf_counter() - started) * 1000)
    except TimeoutError as error:
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    finally:
        stop.set()
    results = []
    for item in raw:
        document = dict(item.get("document", {}))
        document["score"] = item.get("score")
        document["index"] = item.get("index")
        scores = dict(document.get("score_details") or {})
        scores.update(item.get("scores", {}))
        if item.get("highlight_terms"):
            scores["retrieval_highlight_terms"] = item["highlight_terms"]
        if scores:
            document["score_details"] = scores
        results.append(document)
    return {"results": results, "total": len(results), "query_time_ms": elapsed_ms}
