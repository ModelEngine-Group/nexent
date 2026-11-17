# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Knowledge file listing, deletion and status."""

import time
from datetime import datetime, timezone
from typing import Any, Dict

from contracts.constants.constants import ASSET_OWNER_ATTACHMENTS_PREFIX
from management.db.file.attachment import file_exists
from fastapi import Depends, Path, Query
from management.services.knowledge_base.common import get_vector_db_core, logger
from management.services.knowledge_base.file_reader import read_knowledge_files
from management.services.knowledge_base.file_projection import merge_lifecycle_files
from infrastructure.agentos_identity import ServicePrincipal
from nexent.vector_database.base import VectorDatabaseCore
from nexent.storage.errors import DeadlineExceeded
from management.services.file.upload import get_file_size

class KnowledgeBaseFileService:
    @staticmethod
    async def list_files(
        index_name: str = Path(..., description="Name of the index"),
        include_chunks: bool = Query(
            False, description="Whether to include text chunks for each file"
        ),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        *,
        user_id: str,
        tenant_id: str,
    ):
        """
        Get file list for the specified index, including files that are not yet stored in ES

        Args:
            index_name: Name of the index
            include_chunks: Whether to include text chunks for each file
            vdb_core: VectorDatabaseCore instance

        Returns:
            Dictionary containing file list
        """
        from management.services.knowledge_base.management import (
            KnowledgeBaseManagementService,
        )

        try:
            lifecycle_rows = await read_knowledge_files(index_name, ServicePrincipal(user_id, tenant_id))
            files_map: Dict[str, Dict[str, Any]] = {}
            total_start_time = time.time()

            logger.info(
                f"[list_files] index={index_name}, include_chunks={include_chunks}"
            )

            # Step 1: Get existing files from ES (includes chunk_count via aggregation)
            step1_start = time.time()
            existing_files = vdb_core.get_documents_detail(index_name)
            step1_duration = time.time() - step1_start
            logger.info(
                f"[list_files:step1] ES get_documents_detail: {len(existing_files)} files in {step1_duration:.3f}s"
            )

            # Step 3: Build files_map from ES data
            step3_start = time.time()
            for file_info in existing_files:
                utc_create_time_str = file_info.get("create_time", "")
                try:
                    utc_create_timestamp = (
                        datetime.strptime(utc_create_time_str, "%Y-%m-%dT%H:%M:%S")
                        .replace(tzinfo=timezone.utc)
                        .timestamp()
                    )
                except (ValueError, TypeError):
                    utc_create_timestamp = time.time()

                path_or_url = file_info.get("path_or_url")
                file_size = file_info.get("file_size", 0)
                # Fall back to the real storage size when the ES record reports
                # zero (e.g. the data-process task could not resolve it), so the
                # KB list never shows a 0-byte document for an existing file.
                if not file_size and path_or_url:
                    try:
                        file_size = get_file_size(
                            file_info.get("source_type", "minio"), path_or_url
                        )
                    except Exception as size_err:
                        logger.warning(
                            "Failed to derive file size for '%s': %s",
                            path_or_url,
                            size_err,
                        )
                        file_size = 0
                file_data = {
                    "path_or_url": path_or_url,
                    "file": file_info.get("filename", ""),
                    "file_size": file_size,
                    "create_time": int(utc_create_timestamp * 1000),
                    "status": "COMPLETED",
                    "latest_task_id": "",
                    "chunk_count": file_info.get("chunk_count", 0),
                    "error_reason": None,
                    "has_error_info": False,
                }
                files_map[path_or_url] = file_data
            step3_duration = time.time() - step3_start
            logger.info(
                f"[list_files:step3] Build files_map from ES: {len(existing_files)} files in {step3_duration:.3f}s"
            )

            merge_lifecycle_files(files_map, lifecycle_rows)

            files = list(files_map.values())
            logger.info(f"[list_files:step4] Total files built: {len(files)}")

            # Unified chunks processing for all files
            if include_chunks:
                step5_start = time.time()
                completed_files_map = {
                    f["path_or_url"]: f for f in files if f["status"] == "COMPLETED"
                }
                completed_count = len(completed_files_map)
                msearch_body = []

                for path_or_url in completed_files_map.keys():
                    msearch_body.append({"index": index_name})
                    msearch_body.append(
                        {
                            "query": {"term": {"path_or_url": path_or_url}},
                            "size": 100,
                            "_source": ["id", "title", "content", "create_time"],
                        }
                    )

                for file_data in files:
                    file_data["chunks"] = []
                    file_data["chunk_count"] = file_data.get("chunk_count", 0)

                if msearch_body:
                    try:
                        msearch_responses = vdb_core.multi_search(
                            body=msearch_body, index_name=index_name
                        )

                        for i, file_path in enumerate(completed_files_map.keys()):
                            response = msearch_responses["responses"][i]
                            file_data = completed_files_map[file_path]

                            if "error" in response:
                                logger.error(
                                    f"Error getting chunks for {file_data.get('path_or_url')}: {response['error']}"
                                )
                                continue

                            chunks = []
                            for hit in response["hits"]["hits"]:
                                source = hit["_source"]
                                chunks.append(
                                    {
                                        "id": source.get("id"),
                                        "title": source.get("title"),
                                        "content": source.get("content"),
                                        "create_time": source.get("create_time"),
                                    }
                                )

                            file_data["chunks"] = chunks
                            # chunk_count from aggregation is already accurate
                            # no need for additional count queries

                    except Exception as e:
                        logger.error(f"Error during msearch for chunks: {str(e)}")
                step5_duration = time.time() - step5_start
                logger.info(
                    f"[list_files:step5] ES msearch chunks: {completed_count} files in {step5_duration:.3f}s"
                )
            else:
                # When include_chunks=False, chunk_count is already accurate from ES aggregation
                # No need for additional count queries - doc_count from terms aggregation is accurate
                for file_data in files:
                    file_data["chunks"] = []
                    # chunk_count is already set from ES aggregation (doc_count)
                    file_data["chunk_count"] = file_data.get("chunk_count", 0)

            for file_data in files:
                file_data["source_available"] = (
                    KnowledgeBaseManagementService._compute_source_available(file_data)
                )

            total_duration = time.time() - total_start_time
            logger.info(
                f"[list_files:complete] index={index_name}, total_files={len(files)}, "
                f"total_duration={total_duration:.3f}s"
            )

            return {"files": files}

        except (TimeoutError, DeadlineExceeded):
            raise
        except Exception as e:
            raise Exception(f"Error getting file list for index {index_name}: {str(e)}")

    @staticmethod
    def _compute_source_available(file_data: Dict[str, Any]) -> bool:
        path_or_url = file_data.get("path_or_url") or ""
        status = file_data.get("status", "")
        if status != "COMPLETED":
            return True
        if path_or_url.startswith(
            (
                "knowledge_base/",
                f"{ASSET_OWNER_ATTACHMENTS_PREFIX}/",
            )
        ):
            return file_exists(path_or_url)
        return True
