# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Prepare original document sources using metadata and pinned image references."""

import asyncio
import logging
import os
import time
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.agentos import ModelMetadata
from contracts.agentos_knowledge import ModelVersion
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeServiceTimeoutError
from contracts.knowledge_collections import (
    KnowledgeCollectionEnsure,
    KnowledgeCollectionEnsured,
)
from contracts.knowledge_documents import KnowledgeDocument
from management.services.knowledge_base.chunks_authorization import (
    chunks_resource_grant,
)
from management.services.knowledge_base.document_append import append_documents
from management.services.knowledge_base.document_images import pin_document_image
from management.services.knowledge_base.file_reader import KnowledgeFileReader
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, DeadlineExceeded, InvalidInput
from nexent.storage.models import OperationContext

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient
from infrastructure.agentos_identity import ServicePrincipal

logger = logging.getLogger(__name__)


async def _prepare(data, actor, model_name, *, context):
    documents = []
    for item in data:
        context.remaining()
        metadata = item.get("metadata", {})
        source = item.get("path_or_url")
        source_type = item.get("source_type")
        filename = item.get("filename", os.path.basename(source) if source and source_type == "local" else "")
        image_url = metadata.get("image_url", "")
        reference = None
        if len(image_url) > 0:
            reference = await run_blocking("knowledge-document-pin", pin_document_image, image_url, actor,
                context=context, lane="control-io", owner="management.knowledge_base")
        documents.append(KnowledgeDocument(content=item.get("content", ""), image_ref=reference, metadata={
            "title": metadata.get("title", ""), "filename": filename, "path_or_url": source,
            "source_type": source_type,
            "language": metadata.get("languages", ["null"])[0] if metadata.get("languages") else "null",
            "author": metadata.get("author", "null"),
            "date": metadata.get("date", time.strftime("%Y-%m-%d", time.gmtime())),
            "create_time": metadata.get("creation_date", time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())),
            "process_source": metadata.get("process_source", "Unstructured"), "file_size": item.get("file_size"),
            "languages": metadata.get("languages", []), "embedding_model_name": model_name,
        }))
    return documents


async def index_documents(index_name, data, actor, *, reader=None, client=None, context=None, operation_seconds=180):
    if (not isinstance(actor, ServicePrincipal) or not isinstance(index_name, str) or not index_name
        or not isinstance(data, (list, tuple)) or type(operation_seconds) not in {int, float}
        or not 0 < operation_seconds <= 180):
        raise InvalidInput()
    owned = Event() if context is None else None
    context = context or OperationContext("knowledge-documents-" + uuid4().hex,
                                         monotonic() + operation_seconds, cancelled=owned)
    threshold = context.remaining()
    reader = reader or KnowledgeFileReader()
    client = client or AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)
    try:
        async with asyncio.timeout(threshold):
            row = await run_blocking("knowledge-document-prepare-resource", reader.knowledge, index_name, actor,
                edit=True, context=context, lane="control-io", owner="management.knowledge_base")
            items = []
            for position, item in enumerate(data):
                if isinstance(item, dict):
                    items.append(item)
                else:
                    logger.warning("knowledge_document_ignored position=%s", position)
            model_id = row["embedding_model_id"]
            if row["index_name"] != index_name:
                raise InvalidInput()
            binding, dimensions, model = None, 1024, None
            if type(model_id) is int and model_id > 0:
                model = await client.get_model(model_id, actor.user_id, actor.tenant_id)
                if (not isinstance(model, ModelMetadata) or model.model_id != model_id
                    or model.model_type not in {"embedding", "multi_embedding"}
                    or items and not model.qualified_name):
                    raise InvalidInput()
                dimensions = model.embedding_dimensions
                if type(dimensions) is not int or dimensions <= 0:
                    raise InvalidInput()
                binding = ModelVersion(model_id=model_id, revision=model.revision)
            elif items:
                raise InvalidInput()
            grant = chunks_resource_grant(row)
            ensured = await client.ensure_knowledge_collection(KnowledgeCollectionEnsure(
                knowledge_id=grant.knowledge_id, expected_revision=grant.revision, dimensions=dimensions,
                model_binding=binding), actor.user_id, actor.tenant_id)
            if (not isinstance(ensured, KnowledgeCollectionEnsured) or ensured.knowledge_id != grant.knowledge_id
                or ensured.expected_revision != grant.revision or ensured.dimensions != dimensions or ensured.present is not True):
                raise Conflict()
            if not items:
                return {"success": True, "message": "No documents to index", "total_indexed": 0, "total_submitted": 0}
            documents = await _prepare(items, actor, model.qualified_name, context=context)
            count = await append_documents(index_name, documents, actor, reader=reader, client=client,
                                            context=context, model_binding=binding)
            context.remaining()
            return {"success": True, "message": f"Successfully indexed {count} documents",
                    "total_indexed": count, "total_submitted": len(documents)}
    except (TimeoutError, DeadlineExceeded, RuntimeServiceTimeoutError) as error:
        logger.warning("knowledge_document_preparation_timeout operation_id=%s threshold_seconds=%s exception_type=%s",
                       context.operation_id, threshold, type(error).__name__)
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    finally:
        if owned is not None:
            owned.set()
