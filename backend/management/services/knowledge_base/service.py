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

import time
from typing import Any, Dict, List, Optional

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




    @staticmethod
    def search_hybrid(
        *,
        index_names: List[str],
        query: str,
        tenant_id: str,
        top_k: int = 10,
        weight_accurate: Optional[float] = None,
        tag_predicates: Optional[List[Dict[str, Any]]] = None,
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
    ):
        """
        Execute a hybrid search that blends accurate and semantic scoring.
        """
        try:
            if not tenant_id:
                raise ValueError("Tenant ID is required for hybrid search")
            if not query or not query.strip():
                raise ValueError("Query text is required for hybrid search")
            if not index_names:
                raise ValueError("At least one index name is required")
            if top_k <= 0:
                raise ValueError("top_k must be greater than 0")
            if weight_accurate and (weight_accurate < 0 or weight_accurate > 1):
                raise ValueError("weight_accurate must be between 0 and 1")

            # Preserve the REST API's historical 0.5 default for ordinary
            # queries. When the caller has not supplied a preference, give
            # digit-containing identifiers more accurate-search influence.
            effective_weight_accurate = weight_accurate
            if effective_weight_accurate is None:
                effective_weight_accurate = (
                    0.7 if any(char.isdigit() for char in query) else 0.5
                )

            # Get embedding model from the first index's knowledge base record
            if not index_names:
                raise ValueError("At least one index name is required")

            embedding_model, model_id, meta = get_embedding_model_by_index_name(
                tenant_id, index_names[0]
            )

            if not embedding_model:
                if meta.get("status") == "needs_config":
                    # Return a clear error indicating model needs to be configured
                    raise KnowledgeBaseNeedsModelConfigError(
                        index_name=index_names[0],
                        message=f"Knowledge base '{index_names[0]}' does not have an embedding model configured. Please select a model in the knowledge base settings.",
                    )
                else:
                    raise ValueError(
                        f"No embedding model found for index '{index_names[0]}'. "
                        f"Please configure an embedding model for this knowledge base."
                    )

            start_time = time.perf_counter()
            raw_results = vdb_core.hybrid_search(
                index_names=index_names,
                query_text=query,
                embedding_model=embedding_model,
                top_k=top_k,
                weight_accurate=effective_weight_accurate,
            )
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)

            formatted_results = []
            for item in raw_results:
                document = dict(item.get("document", {}))
                document["score"] = item.get("score")
                document["index"] = item.get("index")
                score_details = dict(document.get("score_details") or {})
                if "scores" in item:
                    score_details.update(item["scores"])
                if item.get("highlight_terms"):
                    score_details["retrieval_highlight_terms"] = item["highlight_terms"]
                if score_details:
                    document["score_details"] = score_details
                formatted_results.append(document)

            if tag_predicates:
                formatted_results = ElasticSearchService._apply_document_tag_predicates(
                    formatted_results,
                    tenant_id=tenant_id,
                    index_names=index_names,
                    tag_predicates=tag_predicates,
                )

            return {
                "results": formatted_results,
                "total": len(formatted_results),
                "query_time_ms": elapsed_ms,
            }
        except KnowledgeBaseNeedsModelConfigError:
            raise
        except ValueError:
            raise
        except Exception as exc:
            logger.error(
                f"Hybrid search failed for indices {index_names}: {exc}",
                exc_info=True,
            )
            raise Exception(f"Error executing hybrid search: {str(exc)}")

    @staticmethod
    def _apply_document_tag_predicates(
        results: List[Dict[str, Any]],
        *,
        tenant_id: str,
        index_names: List[str],
        tag_predicates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        from management.services.knowledge_base.tag_projection import (
            LOCAL_DOCUMENT_PROVIDER,
            decode_document_resource_id,
        )
        from management.services.tag.library import TagManagementService

        allowed_paths_by_index: Dict[str, set] = {}
        for index in index_names:
            resource_ids = TagManagementService.filter_document_ids_by_predicates(
                tenant_id, LOCAL_DOCUMENT_PROVIDER, index, tag_predicates
            )
            allowed_paths = set()
            for resource_id in resource_ids:
                try:
                    provider, knowledge_base_id, document_id = (
                        decode_document_resource_id(resource_id)
                    )
                except ValueError:
                    continue
                if provider == LOCAL_DOCUMENT_PROVIDER and knowledge_base_id == index:
                    allowed_paths.add(document_id)
            allowed_paths_by_index[index] = allowed_paths

        return [
            document
            for document in results
            if document.get("path_or_url")
            in allowed_paths_by_index.get(document.get("index"), set())
        ]
