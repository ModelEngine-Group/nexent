# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""
Elasticsearch Application Interface Module

This module provides REST API interfaces for interacting with Elasticsearch, including index management, document
operations, and search functionality.
Main features include:
1. Index creation, deletion, and querying
2. Document indexing, deletion, and searching
3. Support for multiple search methods: exact search, semantic search, and hybrid search
4. Health check interface
"""

from typing import Any, List, Optional

from fastapi import Depends
from management.services.knowledge_base.common import (
    ALLOWED_CHUNK_FIELDS,
    KnowledgeBaseNeedsModelConfigError,
    _rethrow_or_plain,
    get_embedding_model_by_index_name,
    get_vector_db_core,
    logger,
)
from management.services.knowledge_base.deletion import (
    KnowledgeBaseDocumentDeletionService,
)
from nexent.vector_database.base import VectorDatabaseCore

__all__ = (
    "ALLOWED_CHUNK_FIELDS",
    "KnowledgeBaseNeedsModelConfigError",
    "get_embedding_model_by_index_name",
    "get_vector_db_core",
    "_rethrow_or_plain",
    "logger",
)


class ElasticSearchService(KnowledgeBaseDocumentDeletionService):
    @staticmethod
    def get_external_file_chunks(
        index_name: str,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
        path_or_url: Optional[str] = None,
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
    ):
        """
        Adapt external DataMate file records to the established chunk-list response.

        Args:
            index_name: Name of the index to query
            page: Page number (1-based) when paginating
            page_size: Page size when paginating
            path_or_url: Optional document filter
            vdb_core: VectorDatabaseCore instance

        Returns:
            Dictionary containing status, chunk list, total, and pagination metadata
        """
        try:
            result = vdb_core.get_index_chunks(
                index_name,
                page=page,
                page_size=page_size,
                path_or_url=path_or_url,
            )
            raw_chunks = result.get("chunks", [])
            total = result.get("total", len(raw_chunks))
            result_page = result.get("page", page)
            result_page_size = result.get("page_size", page_size)

            filtered_chunks: List[Any] = []
            for chunk in raw_chunks:
                if isinstance(chunk, dict):
                    filtered_chunks.append(
                        {
                            field: chunk.get(field)
                            for field in ALLOWED_CHUNK_FIELDS
                            if field in chunk
                        }
                    )
                else:
                    filtered_chunks.append(chunk)

            return {
                "status": "success",
                "message": f"Successfully retrieved {len(filtered_chunks)} chunks from index {index_name}",
                "chunks": filtered_chunks,
                "total": total,
                "page": result_page,
                "page_size": result_page_size,
            }
        except Exception as e:
            error_msg = f"Error retrieving chunks from index {index_name}: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)
