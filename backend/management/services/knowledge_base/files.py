"""Knowledge file listing, deletion and status."""

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from consts.const import ASSET_OWNER_ATTACHMENTS_PREFIX
from consts.error_code import ErrorCode
from consts.exceptions import AppException
from database.attachment_db import delete_file, file_exists
from database.knowledge_db import get_knowledge_record
from database.knowledge_file_lifecycle_db import list_file_records
from database.knowledge_storage_object_db import list_committed_storage_objects
from fastapi import Depends, Path, Query
from management.services.knowledge_base.common import get_vector_db_core, logger
from management.services.knowledge_base.status import get_all_files_status
from nexent.vector_database.base import VectorDatabaseCore
from services.knowledge_storage_service import (
    release_storage_charge,
    resolve_storage_reference,
)
from services.redis_service import get_redis_service
from utils.file_management_utils import get_file_size
from utils.storage_key_utils import build_preview_pdf_object_key

KNOWLEDGE_BASE_DELETE_BLOCKING_STATUSES = frozenset(
    {
        "UPLOADING",
        "UPLOADED",
        "PROCESSING",
        "FORWARDING",
    }
)


class KnowledgeBaseFileService:
    @staticmethod
    def _assert_knowledge_base_delete_allowed(index_name: str) -> List[Dict[str, Any]]:
        """Raise an EDS conflict when files are still being ingested.

        Lifecycle rows are the durable source of truth for this precondition.
        ``DELETE_REQUESTED`` and ``DELETED`` rows are deliberately ignored:
        they are already owned by the deletion path and must not block a
        broader knowledge-base deletion. The rows are returned so the caller
        can clean up lifecycle records after external deletion succeeds.
        """
        try:
            lifecycle_rows = list_file_records(
                index_name=index_name,
                include_hidden=True,
            )
        except Exception as exc:
            logger.exception(
                "Failed to read lifecycle records before deleting knowledge base '%s'",
                index_name,
            )
            raise AppException(
                ErrorCode.SYSTEM_DATABASE_ERROR,
                details={
                    "operation": "knowledge_base_delete_guard",
                    "index_name": index_name,
                },
            ) from exc

        blocking_files = []
        for row in lifecycle_rows:
            status = str(row.get("status") or "").upper()
            if status not in KNOWLEDGE_BASE_DELETE_BLOCKING_STATUSES:
                continue
            blocking_files.append(
                {
                    "file_id": row.get("file_id"),
                    "file_name": (
                        row.get("original_filename")
                        or row.get("object_name")
                        or row.get("file_id")
                        or "unknown"
                    ),
                    "status": status,
                }
            )

        if blocking_files:
            logger.info(
                "Blocking deletion of knowledge base '%s': %d file(s) are still being processed",
                index_name,
                len(blocking_files),
            )
            raise AppException(
                ErrorCode.KNOWLEDGE_DELETE_BLOCKED,
                details={
                    "index_name": index_name,
                    "blocking_files": blocking_files,
                },
            )

        return lifecycle_rows

    @staticmethod
    async def _delete_kb_source_objects(
        index_name: str,
        vdb_core: VectorDatabaseCore,
        updated_by: Optional[str] = None,
    ) -> Dict[str, int]:
        """Delete the canonical union of ES references and active ledger objects."""
        from management.services.knowledge_base.management import (
            KnowledgeBaseManagementService,
        )

        try:
            knowledge = get_knowledge_record({"index_name": index_name}) or {}
        except Exception:
            logger.exception(
                "Failed to retrieve knowledge record for index '%s'",
                index_name,
            )
            knowledge = {}
        tenant_id = knowledge.get("tenant_id")
        knowledge_id = knowledge.get("knowledge_id")

        ledger_objects: List[Dict[str, Any]] = []
        if tenant_id and knowledge_id is not None:
            try:
                ledger_objects = (
                    list_committed_storage_objects(
                        tenant_id=tenant_id,
                        knowledge_id=knowledge_id,
                    )
                    or []
                )
            except Exception:
                logger.exception(
                    "Failed to retrieve active storage ledger objects for index '%s'",
                    index_name,
                )

        try:
            file_list_result = await KnowledgeBaseManagementService.list_files(
                index_name,
                include_chunks=False,
                vdb_core=vdb_core,
            )
            files_to_delete = file_list_result.get("files", [])
        except Exception:
            logger.exception(
                "Failed to retrieve file list for index '%s'",
                index_name,
            )
            files_to_delete = []

        targets, invalid_entries = (
            KnowledgeBaseManagementService._collect_kb_source_targets(
                ledger_objects,
                files_to_delete,
            )
        )

        deleted_count = 0
        failed_count = invalid_entries
        for target in targets.values():
            if KnowledgeBaseManagementService._delete_kb_source_target(
                target=target,
                tenant_id=tenant_id,
                updated_by=updated_by,
            ):
                deleted_count += 1
            else:
                failed_count += 1

        logger.info(
            "MinIO file deletion summary for index '%s': %s succeeded, %s failed.",
            index_name,
            deleted_count,
            failed_count,
        )
        return {
            "total_files_found": len(targets) + invalid_entries,
            "deleted_count": deleted_count,
            "failed_count": failed_count,
        }

    @staticmethod
    def _collect_kb_source_targets(
        ledger_objects: List[Dict[str, Any]],
        es_files: List[Dict[str, Any]],
    ) -> tuple[Dict[tuple, Dict[str, str]], int]:
        """Build canonical deletion targets and skip ambiguous ES references."""
        targets: Dict[tuple, Dict[str, str]] = {}
        ledger_aliases = set()
        for row in ledger_objects:
            bucket_name = row.get("bucket_name")
            object_name = row.get("object_name")
            if not bucket_name or not object_name:
                continue
            identity = (bucket_name, object_name)
            targets[identity] = {
                "bucket_name": bucket_name,
                "object_name": object_name,
            }
            ledger_aliases.update(
                {
                    object_name,
                    f"s3://{bucket_name}/{object_name}",
                    f"/{bucket_name}/{object_name}",
                }
            )

        invalid_entries = 0
        for file_info in es_files:
            raw_path = file_info.get("path_or_url")
            if not raw_path or raw_path in ledger_aliases:
                invalid_entries += int(not raw_path)
                continue
            reference = resolve_storage_reference(raw_path)
            if reference is None:
                invalid_entries += 1
                logger.warning(
                    "Skipping non-canonical KB source reference during deletion"
                )
                continue
            identity = (reference.bucket_name, reference.object_name)
            targets.setdefault(
                identity,
                {
                    "bucket_name": reference.bucket_name,
                    "object_name": reference.object_name,
                },
            )
        return targets, invalid_entries

    @staticmethod
    def _delete_kb_source_target(
        *,
        target: Dict[str, str],
        tenant_id: Optional[str],
        updated_by: Optional[str],
    ) -> bool:
        """Delete one canonical source target and release its ledger charge."""
        object_name = target["object_name"]
        bucket_name = target["bucket_name"]
        try:
            delete_result = delete_file(object_name=object_name, bucket=bucket_name)
            if not delete_result.get("success"):
                logger.error("Failed to delete a canonical KB source object from MinIO")
                return False
        except Exception:
            logger.exception("Failed to delete a canonical KB source object from MinIO")
            return False

        if tenant_id:
            try:
                release_storage_charge(
                    tenant_id=tenant_id,
                    bucket_name=bucket_name,
                    object_name=object_name,
                    updated_by=updated_by,
                )
            except Exception:
                logger.exception(
                    "Failed to release a deleted KB source object's charge"
                )
        return True

    @staticmethod
    async def list_files(
        index_name: str = Path(..., description="Name of the index"),
        include_chunks: bool = Query(
            False, description="Whether to include text chunks for each file"
        ),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
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

            # Step 2: Get celery task statuses from external service
            step2_start = time.time()
            celery_task_files = await get_all_files_status(index_name)
            step2_duration = time.time() - step2_start
            logger.info(
                f"[list_files:step2] Celery task status: {len(celery_task_files)} tasks in {step2_duration:.3f}s"
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

            # Step 4: Merge celery task data (Redis progress already fetched in get_all_files_status)
            step4_start = time.time()
            celery_file_count = 0
            for path_or_url, status_info in celery_task_files.items():
                celery_file_count += 1
                status_dict = status_info if isinstance(status_info, dict) else {}

                source_type = (
                    status_dict.get("source_type")
                    if status_dict.get("source_type")
                    else "minio"
                )
                original_filename = status_dict.get("original_filename")
                filename = original_filename or (
                    os.path.basename(path_or_url) if path_or_url else ""
                )

                file_size = 0
                if path_or_url in files_map:
                    file_size = files_map[path_or_url].get("file_size", 0)
                else:
                    try:
                        file_size = get_file_size(source_type or "minio", path_or_url)
                    except Exception as size_err:
                        logger.error(
                            f"Failed to get file size for '{path_or_url}': {size_err}"
                        )
                        file_size = 0

                # Get progress from celery_task_files (already includes Redis batch data)
                processed_chunks = status_dict.get("processed_chunks")
                total_chunks = status_dict.get("total_chunks")
                task_id = status_dict.get("latest_task_id", "")

                if path_or_url in files_map:
                    file_data = files_map[path_or_url]
                else:
                    legacy_created_at = status_dict.get("created_at")
                    try:
                        if isinstance(legacy_created_at, (int, float)):
                            legacy_timestamp = (
                                float(legacy_created_at) / 1000
                                if legacy_created_at > 10_000_000_000
                                else float(legacy_created_at)
                            )
                        else:
                            legacy_timestamp = datetime.fromisoformat(
                                str(legacy_created_at).replace("Z", "+00:00")
                            ).timestamp()
                    except (TypeError, ValueError, OverflowError):
                        legacy_timestamp = time.time()
                    file_data = {
                        "path_or_url": path_or_url,
                        "file": filename,
                        "file_size": file_size,
                        "create_time": int(legacy_timestamp * 1000),
                        "chunk_count": 0,
                        "error_reason": None,
                        "has_error_info": False,
                    }
                    files_map[path_or_url] = file_data

                file_data["status"] = status_dict.get(
                    "state", file_data.get("status", "UNKNOWN")
                )
                file_data["latest_task_id"] = task_id
                file_data["processed_chunk_num"] = processed_chunks
                file_data["total_chunk_num"] = total_chunks

                # Get error reason for failed documents (fetch from Redis batch if needed)
                if task_id and status_dict.get("state") in [
                    "PROCESS_FAILED",
                    "FORWARD_FAILED",
                ]:
                    try:
                        redis_service = get_redis_service()
                        error_reason = redis_service.get_error_info(task_id)
                        if error_reason:
                            file_data["error_reason"] = error_reason
                            file_data["has_error_info"] = True
                    except Exception:
                        pass  # Error info is optional, don't fail the request
            step4_duration = time.time() - step4_start
            logger.info(
                f"[list_files:step4] Merge celery tasks: {celery_file_count} tasks in {step4_duration:.3f}s"
            )

            # Durable lifecycle rows are authoritative for upload failures,
            # timestamps, and deletion tombstones. If the migration is not
            # present yet, retain the legacy ES/Redis result unchanged.
            try:
                knowledge_record = (
                    get_knowledge_record({"index_name": index_name}) or {}
                )
                lifecycle_rows = list_file_records(
                    index_name=index_name,
                    tenant_id=knowledge_record.get("tenant_id"),
                    include_hidden=True,
                )
                hidden_paths = {
                    row.get("object_name")
                    for row in lifecycle_rows
                    if row.get("status") in {"DELETE_REQUESTED", "DELETED"}
                    and row.get("object_name")
                }
                for hidden_path in hidden_paths:
                    files_map.pop(hidden_path, None)

                status_map = {
                    "UPLOADING": "WAIT_FOR_PROCESSING",
                    "UPLOADED": "WAIT_FOR_PROCESSING",
                    "PROCESSING": "PROCESSING",
                    "FORWARDING": "FORWARDING",
                    "COMPLETED": "COMPLETED",
                }
                for row in lifecycle_rows:
                    if row.get("status") in {"DELETE_REQUESTED", "DELETED"}:
                        continue
                    path_or_url = row.get("object_name")
                    row_key = path_or_url or f"lifecycle:{row.get('file_id')}"
                    existing = files_map.get(path_or_url) if path_or_url else None
                    timestamp_value = row.get("uploaded_at") or row.get("create_time")
                    try:
                        timestamp = datetime.fromisoformat(
                            str(timestamp_value).replace("Z", "+00:00")
                        ).timestamp()
                    except (TypeError, ValueError, OverflowError):
                        timestamp = time.time()
                    lifecycle_status = row.get("status") or "UPLOADING"
                    if lifecycle_status == "FAILED":
                        lifecycle_status = (
                            "FORWARD_FAILED"
                            if str(
                                row.get("error_stage") or row.get("stage") or ""
                            ).upper()
                            in {"FORWARD", "FORWARDING"}
                            else "PROCESS_FAILED"
                        )
                    # Keep the pre-lifecycle display contract for rows that still
                    # have an ES/Redis name. New rows synchronize the same effective
                    # name into PG after conflict resolution; PG is the fallback when
                    # no legacy name is available (for example after Redis expiry).
                    lifecycle_filename = row.get("original_filename") or ""
                    legacy_filename = (existing or {}).get("file") or ""
                    display_filename = legacy_filename or lifecycle_filename
                    file_data = existing or {
                        "path_or_url": path_or_url,
                        "file": display_filename,
                        "file_size": row.get("file_size") or 0,
                        "create_time": int(timestamp * 1000),
                        "chunk_count": 0,
                        "error_reason": None,
                        "has_error_info": False,
                    }
                    file_data.update(
                        {
                            "path_or_url": path_or_url,
                            "file": display_filename or file_data.get("file", ""),
                            "file_size": row.get("file_size")
                            if row.get("file_size") is not None
                            else file_data.get("file_size", 0),
                            "create_time": int(timestamp * 1000),
                            "status": status_map.get(
                                lifecycle_status, lifecycle_status
                            ),
                            "latest_task_id": row.get("forward_task_id")
                            or row.get("process_task_id")
                            or "",
                            "file_id": row.get("file_id"),
                            "error_reason": row.get("error_message")
                            or row.get("error_code"),
                            "error_code": row.get("error_code"),
                            "error_stage": row.get("error_stage") or row.get("stage"),
                            "failed_at": row.get("failed_at"),
                            "has_error_info": bool(
                                row.get("error_message") or row.get("error_code")
                            ),
                        }
                    )
                    files_map[row_key] = file_data
            except Exception as lifecycle_exc:
                logger.warning(
                    "[list_files] Lifecycle table unavailable; using legacy ES/Redis data: %s",
                    lifecycle_exc,
                )

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

    @staticmethod
    def delete_source_file(
        path_or_url: str,
        tenant_id: Optional[str] = None,
        updated_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Remove MinIO source (and preview cache); does not touch Elasticsearch."""
        minio_result = delete_file(path_or_url)
        deleted_minio = bool(minio_result.get("success"))

        if deleted_minio and tenant_id:
            reference = resolve_storage_reference(path_or_url)
            if reference:
                try:
                    release_storage_charge(
                        tenant_id=tenant_id,
                        bucket_name=reference.bucket_name,
                        object_name=reference.object_name,
                        updated_by=updated_by,
                    )
                except Exception:
                    logger.exception(
                        "Failed to release storage charge after deleting '%s'",
                        path_or_url,
                    )

        if path_or_url.startswith("knowledge_base/"):
            preview_key = build_preview_pdf_object_key(path_or_url)
            try:
                if file_exists(preview_key):
                    delete_file(preview_key)
            except Exception as exc:
                logger.warning(
                    "Failed to delete preview cache for '%s': %s",
                    path_or_url,
                    exc,
                )

        return {"deleted_minio": deleted_minio}
