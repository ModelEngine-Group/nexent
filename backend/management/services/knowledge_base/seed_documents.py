# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Write official text seeds through the standard authorized AgentOS chunk path."""

import time

from contracts.knowledge import ChunkCreateRequest
from management.services.knowledge_base.chunk_creation import create_manual_chunk


async def index_seed_texts(index_name, documents, actor, *, embedding_model_name):
    indexed = 0
    for document in documents:
        if not document.content:
            continue
        now = time.time()
        payload = ChunkCreateRequest(
            content=document.content, chunk_id=f"{int(now)}_{hash(document.content)}"[:20],
            title=document.file_name, filename=document.file_name, path_or_url=document.file_name,
            metadata={
                "source_type": "local", "language": "null", "author": "null",
                "date": time.strftime("%Y-%m-%d", time.gmtime(now)),
                "create_time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)),
                "process_source": "Unstructured", "file_size": 0, "languages": [],
                "embedding_model_name": embedding_model_name,
            },
        )
        await create_manual_chunk(index_name, payload, actor)
        indexed += 1
    return indexed
