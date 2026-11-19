# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Write official text seeds through the standard authorized AgentOS chunk path."""

import time

from contracts.agentos import ModelMetadata
from contracts.constants import environment
from contracts.knowledge_documents import KnowledgeDocument
from management.services.knowledge_base.document_append import append_documents
from nexent.storage.errors import InvalidInput

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient


async def get_seed_model_name(model_id, actor):
    """Read the original qualified source name without constructing an SDK model."""
    client = AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)
    model = await client.get_model(model_id, actor.user_id, actor.tenant_id)
    if (not isinstance(model, ModelMetadata) or model.model_id != model_id
        or model.model_type not in {'embedding', 'multi_embedding'} or not model.qualified_name):
        raise InvalidInput()
    return model.qualified_name


async def index_seed_texts(index_name, documents, actor, *, embedding_model_name):
    prepared = []
    for document in documents:
        if not document.content:
            continue
        now = time.time()
        payload = KnowledgeDocument(
            content=document.content,
            metadata={
                "title": document.file_name, "filename": document.file_name, "path_or_url": document.file_name,
                "source_type": "local", "language": "null", "author": "null",
                "date": time.strftime("%Y-%m-%d", time.gmtime(now)),
                "create_time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)),
                "process_source": "Unstructured", "file_size": 0, "languages": [],
                "embedding_model_name": embedding_model_name,
            },
        )
        prepared.append(payload)
    return await append_documents(index_name, prepared, actor)
