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
import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, Path, Query
from fastapi.responses import StreamingResponse
from nexent.vector_database.base import VectorDatabaseCore

from consts.const import (
    LANGUAGE,
)
from consts.model import ChunkCreateRequest, ChunkUpdateRequest
from database.knowledge_db import (
    get_knowledge_record,
    update_knowledge_record,
    update_last_summary_time,
)
from management.services.model.resolver import (
    get_embedding_model_by_id,
)



from management.services.knowledge_base.common import (
    ALLOWED_CHUNK_FIELDS,
    _update_progress,
    KnowledgeBaseNeedsModelConfigError,
    get_embedding_model_by_index_name,
    get_vector_db_core,
    _rethrow_or_plain,
    check_knowledge_base_exist_impl,
    logger,
)


from management.services.knowledge_base.deletion import KnowledgeBaseDocumentDeletionService

__all__ = ('ALLOWED_CHUNK_FIELDS', '_update_progress', 'KnowledgeBaseNeedsModelConfigError', 'get_embedding_model_by_index_name', 'get_vector_db_core', '_rethrow_or_plain', 'check_knowledge_base_exist_impl', 'logger')

class ElasticSearchService(KnowledgeBaseDocumentDeletionService):
    @staticmethod
    def health_check(vdb_core: VectorDatabaseCore = Depends(get_vector_db_core)):
        """
        Check the health status of the API and Elasticsearch

        Args:
            vdb_core: VectorDatabaseCore instance

        Returns:
            Response containing health status information
        """
        try:
            # Try to list indices as a health check
            indices = vdb_core.get_user_indices()
            return {
                "status": "healthy",
                "elasticsearch": "connected",
                "indices_count": len(indices)
            }
        except Exception as e:
            raise Exception(f"Health check failed: {str(e)}")

    async def summary_index_name(self,
                                 index_name: str = Path(
                                     ..., description="Name of the index to get documents from"),
                                 batch_size: int = Query(
                                     1000, description="Number of documents to retrieve per batch"),
                                 vdb_core: VectorDatabaseCore = Depends(
                                     get_vector_db_core),
                                 user_id: Optional[str] = Body(
                                     None, description="ID of the user delete the knowledge base"),
                                 tenant_id: Optional[str] = Body(
                                     None, description="ID of the tenant"),
                                 language: str = LANGUAGE["ZH"],
                                 model_id: Optional[int] = None
                                 ):
        """
        Generate a summary for the specified index using advanced Map-Reduce approach

        New implementation:
        1. Get documents and cluster them by semantic similarity
        2. Map: Summarize each document individually
        3. Reduce: Merge document summaries into cluster summaries
        4. Return: Combined knowledge base summary

        Args:
            index_name: Name of the index to summarize
            batch_size: Number of documents to sample (default: 1000)
            vdb_core: VectorDatabaseCore instance
            user_id: ID of the user delete the knowledge base
            tenant_id: ID of the tenant
            language: Language of the summary (default: 'zh')
            model_id: Model ID for LLM summarization

        Returns:
            StreamingResponse containing the generated summary
        """
        try:
            if not tenant_id:
                raise Exception(
                    "Tenant ID is required for summary generation.")

            from utils.document_vector_utils import (
                process_documents_for_clustering,
                kmeans_cluster_documents,
                summarize_clusters_map_reduce,
                merge_cluster_summaries
            )
            # Use new Map-Reduce approach
            # Sample reasonable number of documents
            sample_count = min(batch_size // 5, 200)

            # Define a helper function to run all blocking operations in a thread pool
            def _generate_summary_sync():
                """Synchronous function that performs all blocking operations"""
                # Step 1: Get documents and calculate embeddings
                document_samples, doc_embeddings = process_documents_for_clustering(
                    index_name=index_name,
                    vdb_core=vdb_core,
                    sample_doc_count=sample_count
                )

                if not document_samples:
                    raise Exception("No documents found in index.")

                # Step 2: Cluster documents (CPU-intensive operation)
                clusters = kmeans_cluster_documents(doc_embeddings, k=None)

                # Step 3: Map-Reduce summarization (contains blocking LLM calls)
                cluster_summaries = summarize_clusters_map_reduce(
                    document_samples=document_samples,
                    clusters=clusters,
                    language=language,
                    doc_max_words=100,
                    cluster_max_words=150,
                    model_id=model_id,
                    tenant_id=tenant_id
                )

                # Step 4: Merge into final summary
                final_summary = merge_cluster_summaries(cluster_summaries)
                return final_summary

            # Run blocking operations in a thread pool to avoid blocking the event loop
            # Use get_running_loop() for better compatibility with modern asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # Fallback for edge cases
                loop = asyncio.get_event_loop()
            final_summary = await loop.run_in_executor(None, _generate_summary_sync)

            # Stream the result
            async def generate_summary():
                try:
                    # Stream the summary character by character
                    for char in final_summary:
                        yield f"data: {{\"status\": \"success\", \"message\": \"{char}\"}}\n\n"
                        await asyncio.sleep(0.01)
                    yield "data: {\"status\": \"completed\"}\n\n"
                except Exception as e:
                    yield f"data: {{\"status\": \"error\", \"message\": \"{e}\"}}\n\n"

            return StreamingResponse(
                generate_summary(),
                media_type="text/event-stream"
            )

        except Exception as e:
            logger.error(
                f"Knowledge base summary generation failed: {str(e)}", exc_info=True)
            raise Exception(f"Failed to generate summary: {str(e)}")

    @staticmethod
    def get_random_documents(
            index_name: str = Path(...,
                                   description="Name of the index to get documents from"),
            batch_size: int = Query(
                1000, description="Maximum number of documents to retrieve"),
            vdb_core: VectorDatabaseCore = Depends(get_vector_db_core)
    ):
        """
        Get random sample of documents from the specified index

        Args:
            index_name: Name of the index to get documents from
            batch_size: Maximum number of documents to retrieve, default 1000
            vdb_core: VectorDatabaseCore instance

        Returns:
            Dictionary containing total count and sampled documents
        """
        try:
            # Get total document count
            total_docs = vdb_core.count_documents(index_name)

            # Construct the random sampling query using random_score
            query = {
                "size": batch_size,  # Limit return size
                "query": {
                    "function_score": {
                        "query": {"match_all": {}},
                        "random_score": {
                            # Use current time as random seed
                            "seed": int(time.time()),
                            "field": "_seq_no"
                        }
                    }
                }
            }

            # Execute the query
            response = vdb_core.search(
                index_name=index_name,
                query=query
            )

            # Extract and process the sampled documents
            sampled_docs = []
            for hit in response['hits']['hits']:
                doc = hit['_source']
                doc['_id'] = hit['_id']  # Add document ID
                sampled_docs.append(doc)

            return {
                "total": total_docs,
                "documents": sampled_docs
            }

        except Exception as e:
            raise Exception(
                f"Error retrieving random documents from index {index_name}: {str(e)}")

    @staticmethod
    def change_summary(
            index_name: str = Path(...,
                                   description="Name of the index to get documents from"),
            summary_result: Optional[str] = Body(
                description="knowledge base summary"),
            user_id: Optional[str] = Body(
                None, description="ID of the user delete the knowledge base")
    ):
        """
        Update the summary for the specified Elasticsearch index

        Args:
            index_name: Name of the index to update
            summary_result: New summary content
            user_id: ID of the user making the update

        Returns:
            Dictionary containing status and updated summary information
        """
        try:
            update_data = {
                "knowledge_describe": summary_result,  # Set the new summary
                "updated_by": user_id,
                "index_name": index_name
            }
            update_knowledge_record(update_data)
            # Update last_summary_time for auto-summary tracking
            update_last_summary_time(index_name)
            return {"status": "success", "message": f"Index {index_name} summary updated successfully",
                    "summary": summary_result}
        except Exception as e:
            raise Exception(f"{str(e)}")

    @staticmethod
    def get_summary(index_name: str = Path(..., description="Name of the index to get documents from")):
        """
        Get the summary for the specified Elasticsearch index

        Args:
            index_name: Name of the index to get summary from

        Returns:
            Dictionary containing status and summary information
        """
        try:
            knowledge_record = get_knowledge_record({'index_name': index_name})
            if knowledge_record:
                summary_result = knowledge_record["knowledge_describe"]
                success_msg = f"Index {index_name} summary retrieved successfully"
                return {"status": "success", "message": success_msg, "summary": summary_result}
            error_detail = f"Unable to get summary for index {index_name}"
            raise Exception(error_detail)
        except Exception as e:
            error_msg = f"Failed to get summary: {str(e)}"
            raise Exception(error_msg)

    @staticmethod
    def get_index_chunks(
        index_name: str,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
        path_or_url: Optional[str] = None,
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
    ):
        """
        Retrieve chunk records for the specified index with optional pagination.

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
                "page_size": result_page_size
            }
        except Exception as e:
            error_msg = f"Error retrieving chunks from index {index_name}: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    @staticmethod
    def create_chunk(
        index_name: str,
        chunk_request: ChunkCreateRequest,
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ):
        """
        Create a manual chunk entry in the specified index.
        Automatically generates and stores embedding for semantic search.
        """
        try:
            # Get knowledge base's embedding model by model_id
            embedding_model_id = None
            if tenant_id:
                try:
                    knowledge_record = get_knowledge_record({
                        "index_name": index_name,
                        "tenant_id": tenant_id
                    })
                    embedding_model_id = knowledge_record.get("embedding_model_id") if knowledge_record else None
                except Exception as e:
                    logger.warning(f"Failed to get embedding model id for index {index_name}: {e}")

            # Generate embedding if we have content and can get embedding model
            embedding_vector = None
            if chunk_request.content:
                try:
                    embedding_model = get_embedding_model_by_id(tenant_id, embedding_model_id)[0] if tenant_id and embedding_model_id else None
                    if embedding_model:
                        embeddings = embedding_model.get_embeddings(chunk_request.content)
                        if embeddings and len(embeddings) > 0:
                            embedding_vector = embeddings[0]
                            logger.debug(f"Generated embedding for chunk in index {index_name}")
                        else:
                            logger.warning(f"Failed to generate embedding for chunk in index {index_name}")
                    else:
                        logger.warning(f"No embedding model available for index {index_name}")
                except Exception as e:
                    logger.warning(f"Failed to generate embedding for chunk: {e}")

            # Build chunk payload
            chunk_payload = ElasticSearchService._build_chunk_payload(
                base_fields={
                    "id": chunk_request.chunk_id or ElasticSearchService._generate_chunk_id(),
                    "title": chunk_request.title,
                    "filename": chunk_request.filename,
                    "path_or_url": chunk_request.path_or_url,
                    "content": chunk_request.content,
                    "created_by": user_id,
                },
                metadata=chunk_request.metadata,
                ensure_create_time=True,
            )

            # Add embedding if generated
            if embedding_vector:
                chunk_payload["embedding"] = embedding_vector
                if embedding_model_id:
                    chunk_payload["embedding_model_id"] = embedding_model_id

            result = vdb_core.create_chunk(index_name, chunk_payload)
            return {
                "status": "success",
                "message": f"Chunk {result.get('id')} created successfully",
                "chunk_id": result.get("id"),
            }
        except Exception as exc:
            logger.error("Error creating chunk in index %s: %s",
                         index_name, exc, exc_info=True)
            raise Exception(f"Error creating chunk: {exc}")

    @staticmethod
    def update_chunk(
        index_name: str,
        chunk_id: str,
        chunk_request: ChunkUpdateRequest,
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ):
        """
        Update a chunk document.
        """
        try:
            update_fields = chunk_request.dict(
                exclude_unset=True, exclude={"metadata"})
            metadata = chunk_request.metadata or {}
            update_payload = ElasticSearchService._build_chunk_payload(
                base_fields={
                    **update_fields,
                    "updated_by": user_id,
                    "update_time": datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%S"),
                },
                metadata=metadata,
                ensure_create_time=False,
            )

            if not update_payload:
                raise ValueError("No update fields supplied.")

            result = vdb_core.update_chunk(
                index_name, chunk_id, update_payload)
            return {
                "status": "success",
                "message": f"Chunk {result.get('id')} updated successfully",
                "chunk_id": result.get("id"),
            }
        except Exception as exc:
            logger.error("Error updating chunk %s in index %s: %s",
                         chunk_id, index_name, exc, exc_info=True)
            raise Exception(f"Error updating chunk: {exc}")

    @staticmethod
    def delete_chunk(
        index_name: str,
        chunk_id: str,
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
    ):
        """
        Delete a chunk document by id.
        """
        try:
            deleted = vdb_core.delete_chunk(index_name, chunk_id)
            if not deleted:
                raise ValueError(
                    f"Chunk {chunk_id} not found in index {index_name}")
            return {
                "status": "success",
                "message": f"Chunk {chunk_id} deleted successfully",
                "chunk_id": chunk_id,
            }
        except Exception as exc:
            logger.error("Error deleting chunk %s in index %s: %s",
                         chunk_id, index_name, exc, exc_info=True)
            raise Exception(f"Error deleting chunk: {exc}")

    @staticmethod
    def search_hybrid(
            *,
            index_names: List[str],
            query: str,
            tenant_id: str,
            top_k: int = 10,
            weight_accurate: Optional[float] = None,
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
            if weight_accurate and (
                weight_accurate < 0 or weight_accurate > 1
            ):
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

            embedding_model, model_id, meta = get_embedding_model_by_index_name(tenant_id, index_names[0])

            if not embedding_model:
                if meta.get("status") == "needs_config":
                    # Return a clear error indicating model needs to be configured
                    raise KnowledgeBaseNeedsModelConfigError(
                        index_name=index_names[0],
                        message=f"Knowledge base '{index_names[0]}' does not have an embedding model configured. Please select a model in the knowledge base settings."
                    )
                else:
                    raise ValueError(
                        f"No embedding model found for index '{index_names[0]}'. "
                        f"Please configure an embedding model for this knowledge base.")

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
                if "scores" in item:
                    document["score_details"] = item["scores"]
                formatted_results.append(document)

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
    def _generate_chunk_id() -> str:
        """Generate a deterministic chunk id."""
        return f"chunk_{uuid.uuid4().hex}"

    @staticmethod
    def _build_chunk_payload(
        base_fields: Dict[str, Any],
        metadata: Optional[Dict[str, Any]],
        ensure_create_time: bool = True,
    ) -> Dict[str, Any]:
        """
        Merge and sanitize chunk payload fields.
        """
        payload = {
            key: value for key, value in (base_fields or {}).items() if value is not None
        }
        if metadata:
            for key, value in metadata.items():
                if value is not None:
                    payload[key] = value

        if ensure_create_time and "create_time" not in payload:
            payload["create_time"] = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S")

        return payload
