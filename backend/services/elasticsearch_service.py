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
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional

from fastapi import Body, Depends, Path, Query
from fastapi.responses import StreamingResponse
from nexent.core.models.embedding_model import OpenAICompatibleEmbedding, JinaEmbedding, BaseEmbedding
from nexent.core.nlp.tokenizer import calculate_term_weights
from nexent.vector_database.elasticsearch_core import ElasticSearchCore

from consts.const import ES_API_KEY, ES_HOST, LANGUAGE
from database.attachment_db import delete_file
from database.knowledge_db import (
    create_knowledge_record,
    delete_knowledge_record,
    get_knowledge_record,
    update_knowledge_record, get_knowledge_info_by_tenant_id, update_model_name_by_index_name,
)
from services.redis_service import get_redis_service
from utils.config_utils import tenant_config_manager, get_model_name_from_config
from utils.file_management_utils import get_all_files_status, get_file_size

# Configure logging
logger = logging.getLogger("elasticsearch_service")




# Old keyword-based summary method removed - replaced with Map-Reduce approach
# See utils/document_vector_utils.py for new implementation


# Initialize ElasticSearchCore instance with HTTPS support
elastic_core = ElasticSearchCore(
    host=ES_HOST,
    api_key=ES_API_KEY,
    verify_certs=False,
    ssl_show_warn=False,
)


def check_knowledge_base_exist_impl(index_name: str, es_core, user_id: str, tenant_id: str) -> dict:
    """
    Check knowledge base existence and handle orphan cases

    Args:
        index_name: Name of the index to check
        es_core: Elasticsearch core instance
        user_id: Current user ID
        tenant_id: Current tenant ID

    Returns:
        dict: Status information about the knowledge base
    """
    # 1. Check index existence in ES and corresponding record in PG
    es_exists = es_core.client.indices.exists(index=index_name)
    pg_record = get_knowledge_record({"index_name": index_name})

    # Case A: Orphan in ES only (exists in ES, missing in PG)
    if es_exists and not pg_record:
        logger.warning(
            f"Detected orphan knowledge base '{index_name}' – present in ES, absent in PG. Deleting ES index only.")
        try:
            es_core.delete_index(index_name)
            # Clean up Redis records related to this index to avoid stale tasks
            try:
                redis_service = get_redis_service()
                redis_cleanup = redis_service.delete_knowledgebase_records(
                    index_name)
                logger.debug(
                    f"Redis cleanup for orphan index '{index_name}': {redis_cleanup['total_deleted']} records removed")
            except Exception as redis_error:
                logger.warning(
                    f"Redis cleanup failed for orphan index '{index_name}': {str(redis_error)}")
            return {
                "status": "error_cleaning_orphans",
                "action": "cleaned_es"
            }
        except Exception as e:
            logger.error(
                f"Failed to delete orphan ES index '{index_name}': {str(e)}")
            # Still return orphan status so frontend knows it requires attention
            return {"status": "error_cleaning_orphans", "error": True}

    # Case B: Orphan in PG only (missing in ES, present in PG)
    if not es_exists and pg_record:
        logger.warning(
            f"Detected orphan knowledge base '{index_name}' – present in PG, absent in ES. Deleting PG record only.")
        try:
            delete_knowledge_record(
                {"index_name": index_name, "user_id": user_id})
            return {"status": "error_cleaning_orphans", "action": "cleaned_pg"}
        except Exception as e:
            logger.error(
                f"Failed to delete orphan PG record for '{index_name}': {str(e)}")
            return {"status": "error_cleaning_orphans", "error": True}

    # Case C: Index/record both absent -> name is available
    if not es_exists and not pg_record:
        return {"status": "available"}

    # Case D: Index and record both exist – check tenant ownership
    record_tenant_id = pg_record.get('tenant_id') if pg_record else None
    if str(record_tenant_id) == str(tenant_id):
        return {"status": "exists_in_tenant"}
    else:
        return {"status": "exists_in_other_tenant"}


def get_es_core():
    # ensure embedding model is latest
    return elastic_core


def get_embedding_model(tenant_id: str):
    # Get the tenant config
    model_config = tenant_config_manager.get_model_config(
        key="EMBEDDING_ID", tenant_id=tenant_id)

    model_type = model_config.get("model_type", "")

    if model_type == "embedding":
        # Get the es core
        return OpenAICompatibleEmbedding(api_key=model_config.get("api_key", ""), base_url=model_config.get("base_url", ""), model_name=get_model_name_from_config(model_config) or "", embedding_dim=model_config.get("max_tokens", 1024))
    elif model_type == "multi_embedding":
        return JinaEmbedding(api_key=model_config.get("api_key", ""), base_url=model_config.get("base_url", ""), model_name=get_model_name_from_config(model_config) or "", embedding_dim=model_config.get("max_tokens", 1024))
    else:
        return None


class ElasticSearchService:
    @staticmethod
    async def full_delete_knowledge_base(index_name: str, es_core: ElasticSearchCore, user_id: str):
        """
        Completely delete a knowledge base, including its index, associated files in MinIO,
        and all related records in Redis and PostgreSQL.
        """
        logger.debug(
            f"Starting full deletion process for knowledge base (index): {index_name}")
        try:
            # 1. Get all files associated with the index from Elasticsearch
            logger.debug(
                f"Step 1/4: Retrieving file list for index: {index_name}")
            try:
                file_list_result = await ElasticSearchService.list_files(index_name, include_chunks=False,
                                                                         es_core=es_core)
                files_to_delete = file_list_result.get("files", [])
                logger.debug(
                    f"Found {len(files_to_delete)} files to delete from MinIO for index '{index_name}'.")
            except Exception as e:
                logger.error(
                    f"Failed to retrieve file list for index '{index_name}': {str(e)}")
                # We can still proceed to delete the index itself even if listing files fails
                files_to_delete = []

            # 2. Delete files from MinIO
            minio_deletion_success_count = 0
            minio_deletion_failure_count = 0
            if files_to_delete:
                logger.debug(
                    f"Step 2/4: Starting deletion of {len(files_to_delete)} files from MinIO.")
                for file_info in files_to_delete:
                    object_name = file_info.get("path_or_url")
                    if not object_name:
                        logger.warning(
                            f"Could not find 'path_or_url' for file entry: {file_info}. Skipping deletion.")
                        minio_deletion_failure_count += 1
                        continue

                    try:
                        logger.debug(
                            f"Deleting object: '{object_name}' from MinIO for index '{index_name}'")
                        delete_result = delete_file(object_name=object_name)
                        if delete_result.get("success"):
                            logger.debug(
                                f"Successfully deleted object: '{object_name}' from MinIO.")
                            minio_deletion_success_count += 1
                        else:
                            minio_deletion_failure_count += 1
                            error_msg = delete_result.get(
                                "error", "Unknown error")
                            logger.error(
                                f"Failed to delete object: '{object_name}' from MinIO. Reason: {error_msg}")
                    except Exception as e:
                        minio_deletion_failure_count += 1
                        logger.error(
                            f"An exception occurred while deleting object: '{object_name}' from MinIO. Error: {str(e)}")

                logger.info(f"MinIO file deletion summary for index '{index_name}': "
                            f"{minio_deletion_success_count} succeeded, {minio_deletion_failure_count} failed.")
            else:
                logger.debug(
                    f"Step 2/4: No files found in index '{index_name}', skipping MinIO deletion.")

            # 3. Delete Elasticsearch index and its DB record
            logger.debug(
                f"Step 3/4: Deleting Elasticsearch index '{index_name}' and its database record.")
            delete_index_result = await ElasticSearchService.delete_index(index_name, es_core, user_id)

            # 4. Clean up Redis records related to this knowledge base
            logger.debug(
                f"Step 4/4: Cleaning up Redis records for index '{index_name}'.")
            redis_cleanup_result = {}
            try:
                from services.redis_service import get_redis_service
                redis_service = get_redis_service()
                redis_cleanup_result = redis_service.delete_knowledgebase_records(
                    index_name)
                logger.debug(f"Redis cleanup for index '{index_name}' completed. "
                             f"Deleted {redis_cleanup_result['total_deleted']} records.")
            except Exception as redis_error:
                logger.error(
                    f"Redis cleanup failed for index '{index_name}': {str(redis_error)}")
                redis_cleanup_result = {"error": str(redis_error)}

            # Construct final result
            result = {
                "status": "success",
                "message": (
                    f"Index {index_name} deleted successfully. "
                    f"MinIO: {minio_deletion_success_count} files deleted, {minio_deletion_failure_count} failed. "
                    f"Redis: Cleaned up {redis_cleanup_result.get('total_deleted', 0)} records."
                ),
                "es_delete_result": delete_index_result,
                "minio_cleanup": {
                    "total_files_found": len(files_to_delete),
                    "deleted_count": minio_deletion_success_count,
                    "failed_count": minio_deletion_failure_count
                },
                "redis_cleanup": redis_cleanup_result
            }

            if "errors" in redis_cleanup_result:
                result["redis_warnings"] = redis_cleanup_result["errors"]

            logger.info(
                f"Successfully completed full deletion process for knowledge base '{index_name}'.")
            return result

        except Exception as e:
            logger.error(
                f"Error during full deletion of index '{index_name}': {str(e)}", exc_info=True)
            raise e

    @staticmethod
    def create_index(
            index_name: str = Path(...,
                                   description="Name of the index to create"),
            embedding_dim: Optional[int] = Query(
                None, description="Dimension of the embedding vectors"),
            es_core: ElasticSearchCore = Depends(get_es_core),
            user_id: Optional[str] = Body(
                None, description="ID of the user creating the knowledge base"),
            tenant_id: Optional[str] = Body(
                None, description="ID of the tenant creating the knowledge base"),
    ):
        try:
            if es_core.client.indices.exists(index=index_name):
                raise Exception(f"Index {index_name} already exists")
            embedding_model = get_embedding_model(tenant_id)
            success = es_core.create_vector_index(index_name, embedding_dim=embedding_dim or (
                embedding_model.embedding_dim if embedding_model else 1024))
            if not success:
                raise Exception(f"Failed to create index {index_name}")
            knowledge_data = {"index_name": index_name,
                              "created_by": user_id,
                              "tenant_id": tenant_id,
                              "embedding_model_name": embedding_model.model}
            create_knowledge_record(knowledge_data)
            return {"status": "success", "message": f"Index {index_name} created successfully"}
        except Exception as e:
            raise Exception(f"Error creating index: {str(e)}")

    @staticmethod
    async def delete_index(
            index_name: str = Path(...,
                                   description="Name of the index to delete"),
            es_core: ElasticSearchCore = Depends(get_es_core),
            user_id: Optional[str] = Body(
                None, description="ID of the user delete the knowledge base"),
    ):
        try:
            # 1. Get list of files from the index
            try:
                files_to_delete = await ElasticSearchService.list_files(index_name, es_core=es_core)
                if files_to_delete and files_to_delete.get("files"):
                    # 2. Delete files from MinIO storage
                    for file_info in files_to_delete["files"]:
                        object_name = file_info.get("path_or_url")
                        source_type = file_info.get("source_type")
                        if object_name and source_type == "minio":
                            logger.info(
                                f"Deleting file {object_name} from MinIO for index {index_name}")
                            delete_file(object_name)
            except Exception as e:
                # Log the error but don't block the index deletion
                logger.error(
                    f"Error deleting associated files from MinIO for index {index_name}: {str(e)}")

            # 3. Delete the index in Elasticsearch
            success = es_core.delete_index(index_name)
            if not success:
                # Even if deletion fails, we proceed to database record cleanup
                logger.warning(
                    f"Index {index_name} not found in Elasticsearch or could not be deleted, but proceeding with DB cleanup.")

            # 4. Delete the knowledge base record from the database
            update_data = {
                "updated_by": user_id,
                "index_name": index_name
            }
            success = delete_knowledge_record(update_data)
            if not success:
                raise Exception(
                    f"Error deleting knowledge record for index {index_name}")

            return {"status": "success", "message": f"Index {index_name} and associated files deleted successfully"}
        except Exception as e:
            raise Exception(f"Error deleting index: {str(e)}")

    @staticmethod
    def list_indices(
            pattern: str = Query(
                "*", description="Pattern to match index names"),
            include_stats: bool = Query(
                False, description="Whether to include index stats"),
            tenant_id: str = Body(
                description="ID of the tenant listing the knowledge base"),
            user_id: str = Body(
                description="ID of the user listing the knowledge base"),
            es_core: ElasticSearchCore = Depends(get_es_core)
    ):
        """
        List all indices that the current user has permissions to access.
        async PG database to sync ES, remove the data that is not in ES

        Args:
            pattern: Pattern to match index names
            include_stats: Whether to include index stats
            tenant_id: ID of the tenant listing the knowledge base
            user_id: ID of the user listing the knowledge base
            es_core: ElasticSearchCore instance

        Returns:
            Dict[str, Any]: A dictionary containing the list of indices and the count.
        """
        all_indices_list = es_core.get_user_indices(pattern)

        db_record = get_knowledge_info_by_tenant_id(tenant_id=tenant_id)

        filtered_indices_list = []
        model_name_is_none_list = []
        for record in db_record:
            # async PG database to sync ES, remove the data that is not in ES
            if record["index_name"] not in all_indices_list:
                delete_knowledge_record(
                    {"index_name": record["index_name"], "user_id": user_id})
                continue
            if record["embedding_model_name"] is None:
                model_name_is_none_list.append(record["index_name"])
            filtered_indices_list.append(record["index_name"])

        indices = [info.get("index") if isinstance(
            info, dict) else info for info in filtered_indices_list]

        response = {
            "indices": indices,
            "count": len(indices)
        }

        if include_stats:
            stats_info = []
            if filtered_indices_list:
                indice_stats = es_core.get_index_stats(filtered_indices_list)
                for index_name in filtered_indices_list:
                    index_stats = indice_stats.get(index_name, {})
                    stats_info.append({
                        "name": index_name,
                        "stats": index_stats
                    })
                    if index_name in model_name_is_none_list:
                        update_model_name_by_index_name(index_name,
                                                        index_stats.get("base_info", {}).get(
                                                            "embedding_model", ""),
                                                        tenant_id, user_id)
            response["indices_info"] = stats_info

        return response

    @staticmethod
    def get_index_name(
            index_name: str = Path(..., description="Name of the index"),
            es_core: ElasticSearchCore = Depends(get_es_core)
    ):
        """
        Get detailed information about the index, including statistics, field mappings, file list, and processing
        information

        Args:
            index_name: Index name
            es_core: ElasticSearchCore instance

        Returns:
            Dictionary containing detailed index information
        """
        try:
            # Get all the info in one combined response
            stats = es_core.get_index_stats([index_name])
            mappings = es_core.get_index_mapping([index_name])

            # Check if stats and mappings are valid
            if stats and index_name in stats:
                index_stats = stats[index_name]
            else:
                logger.error(f"404: Index {index_name} not found in stats")
                index_stats = {}

            if mappings and index_name in mappings:
                fields = mappings[index_name]
            else:
                logger.error(f"404: Index {index_name} not found in mappings:")
                fields = []

            # Check if base_info exists in stats
            search_performance = {}
            if index_stats and "base_info" in index_stats:
                base_info = index_stats["base_info"]
                search_performance = index_stats.get("search_performance", {})
            else:
                logger.error(f"404: Index {index_name} may not be created yet")
                base_info = {
                    "doc_count": 0,
                    "unique_sources_count": 0,
                    "store_size": "0",
                    "process_source": "Unknown",
                    "embedding_model": "Unknown",
                }

            return {
                "base_info": base_info,
                "search_performance": search_performance,
                "fields": fields
            }
        except Exception as e:
            error_msg = str(e)
            # Check if it's an ElasticSearch connection issue
            if "503" in error_msg or "search_phase_execution_exception" in error_msg:
                raise Exception(
                    f"ElasticSearch service unavailable for index {index_name}: {error_msg}")
            elif "ApiError" in error_msg:
                raise Exception(
                    f"ElasticSearch API error for index {index_name}: {error_msg}")
            else:
                raise Exception(
                    f"Error getting info for index {index_name}: {error_msg}")

    @staticmethod
    def index_documents(
            embedding_model: BaseEmbedding,
            index_name: str = Path(..., description="Name of the index"),
            data: List[Dict[str, Any]
                       ] = Body(..., description="Document List to process"),
            es_core: ElasticSearchCore = Depends(get_es_core)
    ):
        """
        Index documents and create vector embeddings, create index if it doesn't exist

        Args:
            embedding_model: Optional embedding model to use for generating document vectors
            index_name: Index name
            data: List containing document data to be indexed
            es_core: ElasticSearchCore instance

        Returns:
            IndexingResponse object containing indexing result information
        """
        try:
            if not index_name:
                raise Exception("Index name is required")

            # Create index if needed (ElasticSearchCore will handle embedding_dim automatically)
            if not es_core.client.indices.exists(index=index_name):
                try:
                    ElasticSearchService.create_index(
                        index_name, es_core=es_core)
                    logger.info(f"Created new index {index_name}")
                except Exception as create_error:
                    raise Exception(
                        f"Failed to create index {index_name}: {str(create_error)}")

            # Transform indexing request results to documents
            documents = []

            for idx, item in enumerate(data):
                # All items should be dictionaries
                if not isinstance(item, dict):
                    logger.warning(f"Skipping item {idx} - not a dictionary")
                    continue

                # Extract metadata
                metadata = item.get("metadata", {})
                source = item.get("path_or_url")
                text = item.get("content", "")
                source_type = item.get("source_type")
                file_size = item.get("file_size")
                file_name = item.get("filename", os.path.basename(
                    source) if source and source_type == "local" else "")

                # Get from metadata
                title = metadata.get("title", "")
                language = metadata.get("languages", ["null"])[
                    0] if metadata.get("languages") else "null"
                author = metadata.get("author", "null")
                date = metadata.get("date", time.strftime(
                    "%Y-%m-%d", time.gmtime()))
                create_time = metadata.get("creation_date", time.strftime(
                    "%Y-%m-%dT%H:%M:%S", time.gmtime()))

                # Set embedding model name from the embedding model
                embedding_model_name = ""
                if embedding_model:
                    embedding_model_name = embedding_model.model

                # Create document
                document = {
                    "title": title,
                    "filename": file_name,
                    "path_or_url": source,
                    "source_type": source_type,
                    "language": language,
                    "author": author,
                    "date": date,
                    "content": text,
                    "process_source": "Unstructured",
                    "file_size": file_size,
                    "create_time": create_time,
                    "languages": metadata.get("languages", []),
                    "embedding_model_name": embedding_model_name
                }

                documents.append(document)

            total_submitted = len(documents)
            if total_submitted == 0:
                return {
                    "success": True,
                    "message": "No documents to index",
                    "total_indexed": 0,
                    "total_submitted": 0
                }

            # Index documents (use default batch_size and content_field)
            try:
                total_indexed = es_core.index_documents(
                    index_name=index_name,
                    embedding_model=embedding_model,
                    documents=documents,
                )

                return {
                    "success": True,
                    "message": f"Successfully indexed {total_indexed} documents",
                    "total_indexed": total_indexed,
                    "total_submitted": total_submitted
                }
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Error during indexing: {error_msg}")
                raise Exception(f"Error during indexing: {error_msg}")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error indexing documents: {error_msg}")
            raise Exception(f"Error indexing documents: {error_msg}")

    @staticmethod
    async def list_files(
            index_name: str = Path(..., description="Name of the index"),
            include_chunks: bool = Query(
                False, description="Whether to include text chunks for each file"),
            es_core: ElasticSearchCore = Depends(get_es_core)
    ):
        """
        Get file list for the specified index, including files that are not yet stored in ES

        Args:
            index_name: Name of the index
            include_chunks: Whether to include text chunks for each file
            es_core: ElasticSearchCore instance

        Returns:
            Dictionary containing file list
        """
        try:
            files = []
            # Get existing files from ES
            existing_files = es_core.get_file_list_with_details(index_name)

            # Get unique celery files list and the status of each file
            celery_task_files = await get_all_files_status(index_name)
            # Create a set of path_or_urls from existing files for quick lookup
            existing_paths = {file_info.get('path_or_url')
                              for file_info in existing_files}

            # For files already stored in ES, add to files list
            for file_info in existing_files:
                utc_create_time_str = file_info.get('create_time', '')
                # Try to parse the create_time string, fallback to current timestamp if format is invalid
                try:
                    utc_create_timestamp = datetime.strptime(utc_create_time_str, '%Y-%m-%dT%H:%M:%S').replace(
                        tzinfo=timezone.utc).timestamp()
                except (ValueError, TypeError):
                    utc_create_timestamp = time.time()

                file_data = {
                    'path_or_url': file_info.get('path_or_url'),
                    'file': file_info.get('filename', ''),
                    'file_size': file_info.get('file_size', 0),
                    'create_time': int(utc_create_timestamp * 1000),
                    'status': "COMPLETED",
                    'latest_task_id': ''
                }
                files.append(file_data)

            # For files not yet stored in ES (files currently being processed)
            for path_or_url, status_info in celery_task_files.items():
                # Skip files that are already in existing_files to avoid duplicates
                if path_or_url not in existing_paths:
                    # Ensure status_info is a dictionary
                    status_dict = status_info if isinstance(
                        status_info, dict) else {}

                    # Get source_type and original_filename, with defaults
                    source_type = status_dict.get('source_type') if status_dict.get(
                        'source_type') else 'minio'
                    original_filename = status_dict.get('original_filename')

                    # Determine the filename
                    filename = original_filename or (
                        os.path.basename(path_or_url) if path_or_url else '')

                    # Safely get file size; default to 0 on any error
                    try:
                        file_size = get_file_size(
                            source_type or 'minio', path_or_url)
                    except Exception as size_err:
                        logger.error(
                            f"Failed to get file size for '{path_or_url}': {size_err}")
                        file_size = 0

                    file_data = {
                        'path_or_url': path_or_url,
                        'file': filename,
                        'file_size': file_size,
                        'create_time': int(time.time() * 1000),
                        'status': status_dict.get('state', 'UNKNOWN'),
                        'latest_task_id': status_dict.get('latest_task_id', '')
                    }
                    files.append(file_data)

            # Unified chunks processing for all files
            if include_chunks:
                # Prepare msearch body for all completed files
                completed_files_map = {
                    f['path_or_url']: f for f in files if f['status'] == "COMPLETED"}
                msearch_body = []

                for path_or_url in completed_files_map.keys():
                    msearch_body.append({'index': index_name})
                    msearch_body.append({
                        "query": {"term": {"path_or_url": path_or_url}},
                        "size": 100,
                        "_source": ["id", "title", "content", "create_time"]
                    })

                # Initialize chunks for all files
                for file_data in files:
                    file_data['chunks'] = []
                    file_data['chunk_count'] = 0

                if msearch_body:
                    try:
                        msearch_responses = es_core.client.msearch(
                            body=msearch_body,
                            index=index_name
                        )

                        for i, file_path in enumerate(completed_files_map.keys()):
                            response = msearch_responses['responses'][i]
                            file_data = completed_files_map[file_path]

                            if 'error' in response:
                                logger.error(
                                    f"Error getting chunks for {file_data.get('path_or_url')}: {response['error']}")
                                continue

                            chunks = []
                            for hit in response["hits"]["hits"]:
                                source = hit["_source"]
                                chunks.append({
                                    "id": source.get("id"),
                                    "title": source.get("title"),
                                    "content": source.get("content"),
                                    "create_time": source.get("create_time")
                                })

                            file_data['chunks'] = chunks
                            file_data['chunk_count'] = len(chunks)

                    except Exception as e:
                        logger.error(
                            f"Error during msearch for chunks: {str(e)}")
            else:
                for file_data in files:
                    file_data['chunks'] = []
                    file_data['chunk_count'] = 0

            return {"files": files}

        except Exception as e:
            raise Exception(
                f"Error getting file list for index {index_name}: {str(e)}")

    @staticmethod
    def delete_documents(
            index_name: str = Path(..., description="Name of the index"),
            path_or_url: str = Query(...,
                                     description="Path or URL of documents to delete"),
            es_core: ElasticSearchCore = Depends(get_es_core)
    ):
        # 1. Delete ES documents
        deleted_count = es_core.delete_documents_by_path_or_url(
            index_name, path_or_url)
        # 2. Delete MinIO file
        minio_result = delete_file(path_or_url)
        return {"status": "success", "deleted_es_count": deleted_count, "deleted_minio": minio_result.get("success")}

    @staticmethod
    def health_check(es_core: ElasticSearchCore = Depends(get_es_core)):
        """
        Check the health status of the API and Elasticsearch

        Args:
            es_core: ElasticSearchCore instance

        Returns:
            Response containing health status information
        """
        try:
            # Try to list indices as a health check
            indices = es_core.get_user_indices()
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
                                 es_core: ElasticSearchCore = Depends(
                                     get_es_core),
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
            es_core: ElasticSearchCore instance
            tenant_id: ID of the tenant
            language: Language of the summary (default: 'zh')
            model_id: Model ID for LLM summarization

        Returns:
            StreamingResponse containing the generated summary
        """
        try:
            from utils.document_vector_utils import (
                process_documents_for_clustering,
                kmeans_cluster_documents,
                summarize_clusters_map_reduce,
                merge_cluster_summaries
            )
            
            if not tenant_id:
                raise Exception("Tenant ID is required for summary generation.")
            
            # Use new Map-Reduce approach
            sample_count = min(batch_size // 5, 200)  # Sample reasonable number of documents
            
            # Step 1: Get documents and calculate embeddings
            document_samples, doc_embeddings = process_documents_for_clustering(
                index_name=index_name,
                es_core=es_core,
                sample_doc_count=sample_count
            )
            
            if not document_samples:
                raise Exception("No documents found in index.")
            
            # Step 2: Cluster documents
            clusters = kmeans_cluster_documents(doc_embeddings, k=None)
            
            # Step 3: Map-Reduce summarization
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
            
            # Stream the result
            async def generate_summary():
                try:
                    # Stream the summary character by character
                    for char in final_summary:
                        yield f"data: {{\"status\": \"success\", \"message\": \"{char}\"}}\n\n"
                        await asyncio.sleep(0.01)
                    yield f"data: {{\"status\": \"completed\"}}\n\n"
                except Exception as e:
                    yield f"data: {{\"status\": \"error\", \"message\": \"{e}\"}}\n\n"
            
            return StreamingResponse(
                generate_summary(),
                media_type="text/event-stream"
            )
            
        except Exception as e:
            logger.error(f"Knowledge base summary generation failed: {str(e)}", exc_info=True)
            raise Exception(f"Failed to generate summary: {str(e)}")

    @staticmethod
    def get_random_documents(
            index_name: str = Path(...,
                                   description="Name of the index to get documents from"),
            batch_size: int = Query(
                1000, description="Maximum number of documents to retrieve"),
            es_core: ElasticSearchCore = Depends(get_es_core)
    ):
        """
        Get random sample of documents from the specified index

        Args:
            index_name: Name of the index to get documents from
            batch_size: Maximum number of documents to retrieve, default 1000
            es_core: ElasticSearchCore instance

        Returns:
            Dictionary containing total count and sampled documents
        """
        try:
            # Get total document count
            count_response = es_core.client.count(index=index_name)
            total_docs = count_response['count']

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
            response = es_core.client.search(
                index=index_name,
                body=query
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
