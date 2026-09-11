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
import json
import time
from typing import Any, Dict, Optional

from fastapi import Depends, Path, Query
from nexent.vector_database.base import VectorDatabaseCore

from consts.const import (
    DOCUMENT_DELETE_DRAIN_TIMEOUT_S,
    DOCUMENT_DELETE_RETRY_INTERVAL_S,
)

from database.attachment_db import delete_file
from database.knowledge_db import (
    get_knowledge_record,
    update_last_doc_update_time,
)
from database.knowledge_file_lifecycle_db import (
    create_delete_tombstone,
    delete_file_record,
    get_file_record,
    transition_file_record,
)
from services.knowledge_storage_service import (
    release_storage_charge,
    resolve_storage_reference,
)
from services.redis_service import get_redis_service
from utils.file_management_utils import get_all_files_status



from management.services.knowledge_base.common import (
    get_vector_db_core,
    logger,
)
from management.services.knowledge_base.management import (
    KNOWLEDGE_BASE_DELETE_BLOCKING_STATUSES,
    KnowledgeBaseManagementService,
)


_document_delete_tasks: Dict[str, asyncio.Task] = {}



class KnowledgeBaseDocumentDeletionService(KnowledgeBaseManagementService):
    DOCUMENT_DELETE_SCOPES = ("source_only", "full")
    @staticmethod
    async def _assert_source_only_deletable(
            index_name: str, path_or_url: str
    ) -> None:
        celery_task_files = await get_all_files_status(index_name)
        status_info = celery_task_files.get(path_or_url)
        if not status_info or not isinstance(status_info, dict):
            return
        state = status_info.get("state") or ""
        if state and state != "COMPLETED":
            raise ValueError(
                f"Cannot delete source file while document is in state '{state}'. "
                "Wait until processing completes or use scope=full to remove the document."
            )

    @staticmethod
    def _mark_file_delete_requested(
            index_name: str,
            path_or_url: str,
            requested_by: Optional[str] = None,
            file_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Install the durable PG/Redis deletion fence before cleanup."""
        try:
            knowledge = get_knowledge_record({"index_name": index_name}) or {}
            tenant_id = knowledge.get("tenant_id")
            knowledge_id = knowledge.get("knowledge_id")
            if tenant_id is None or knowledge_id is None:
                return None
            record = get_file_record(
                file_id=file_id,
                tenant_id=tenant_id,
                index_name=index_name,
                object_name=path_or_url if not file_id else None,
                include_hidden=True,
            )
            if record:
                if str(record.get("status") or "").upper() not in {"DELETE_REQUESTED", "DELETED"}:
                    record = transition_file_record(
                        record["file_id"],
                        status="DELETE_REQUESTED",
                        stage="DELETE",
                        expected_statuses=(
                            "UPLOADING", "UPLOADED", "PROCESSING", "FORWARDING", "FAILED", "COMPLETED"
                        ),
                        updated_by=requested_by,
                    ) or record
            elif tenant_id is not None and knowledge_id is not None:
                record = create_delete_tombstone(
                    tenant_id=str(tenant_id),
                    knowledge_id=int(knowledge_id),
                    index_name=index_name,
                    object_name=path_or_url,
                    requested_by=requested_by,
                    file_id=file_id,
                )
            try:
                fence_ok = get_redis_service().mark_document_delete_requested(
                    file_id=(record or {}).get("file_id") or file_id,
                    requested_by=requested_by,
                )
                if not fence_ok:
                    logger.warning(
                        "Redis deletion fence unavailable; PG status remains the fallback index=%s path=%s",
                        index_name,
                        path_or_url,
                    )
            except Exception as fence_exc:
                logger.warning("Failed to install Redis deletion fence: %s", fence_exc)
            return record
        except Exception as lifecycle_exc:
            logger.warning(
                "Failed to write deletion tombstone for index=%s path=%s: %s",
                index_name,
                path_or_url,
                lifecycle_exc,
            )
            return None

    @staticmethod
    def _mark_file_deleted(
            index_name: str,
            path_or_url: str,
            file_id: Optional[str] = None,
            updated_by: Optional[str] = None,
    ) -> None:
        try:
            knowledge = get_knowledge_record({"index_name": index_name}) or {}
            record = get_file_record(
                file_id=file_id,
                tenant_id=knowledge.get("tenant_id"),
                index_name=index_name,
                object_name=path_or_url if not file_id else None,
                include_hidden=True,
            )
            if record:
                delete_file_record(
                    record["file_id"],
                    expected_statuses=("DELETE_REQUESTED", "DELETED"),
                )
        except Exception as lifecycle_exc:
            logger.warning(
                "Failed to finalize deletion tombstone for index=%s path=%s: %s",
                index_name,
                path_or_url,
                lifecycle_exc,
            )

    @staticmethod
    def _cancel_document_tasks(*, lifecycle_record: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Revoke Celery tasks recorded for one lifecycle file."""
        task_ids = {
            lifecycle_record.get(field)
            for field in ("process_task_id", "forward_task_id", "parent_task_id")
            if lifecycle_record and lifecycle_record.get(field)
        }
        file_id = (lifecycle_record or {}).get("file_id")
        try:
            from data_process.app import app as celery_app

            inspector = celery_app.control.inspect(timeout=0.5)
            for method_name in ("active", "reserved"):
                try:
                    workers = getattr(inspector, method_name)() or {}
                except Exception as inspect_exc:
                    logger.debug("Unable to inspect %s Celery tasks: %s", method_name, inspect_exc)
                    continue
                for worker_tasks in workers.values():
                    for task in worker_tasks or []:
                        kwargs = task.get("kwargs") or {}
                        if isinstance(kwargs, str):
                            try:
                                kwargs = json.loads(kwargs)
                            except Exception:
                                kwargs = {}
                        if file_id and isinstance(kwargs, dict) and kwargs.get("file_id") == file_id and task.get("id"):
                            task_ids.add(task["id"])
        except Exception as inspect_exc:
            logger.debug("Celery task inspection unavailable during document deletion: %s", inspect_exc)

        cancelled = []
        try:
            redis_service = get_redis_service()
        except Exception:
            redis_service = None
        try:
            from data_process.app import app as celery_app
        except Exception:
            celery_app = None
        for task_id in sorted(task_ids):
            if redis_service:
                try:
                    redis_service.mark_task_cancelled(task_id)
                except Exception as cancel_exc:
                    logger.debug("Unable to mark task %s cancelled: %s", task_id, cancel_exc)
            if celery_app:
                try:
                    celery_app.control.revoke(task_id, terminate=False)
                except Exception as revoke_exc:
                    logger.debug("Unable to revoke task %s: %s", task_id, revoke_exc)
            cancelled.append(task_id)
        return {"task_ids": cancelled, "cancelled_count": len(cancelled)}

    @staticmethod
    def _wait_for_document_tasks(
            *, index_name: str, path_or_url: str, lifecycle_record: Dict[str, Any],
            timeout_seconds: float, poll_interval_seconds: float = 0.2,
    ) -> bool:
        """Wait for the recorded parent chain to reach a terminal state."""
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        task_id = lifecycle_record.get("parent_task_id")
        if not task_id:
            status = str(lifecycle_record.get("status") or "").upper()
            return status not in KNOWLEDGE_BASE_DELETE_BLOCKING_STATUSES
        while True:
            try:
                task_data = get_redis_service().backend_client.get(f"celery-task-meta-{task_id}")
                if task_data:
                    if isinstance(task_data, bytes):
                        task_data = task_data.decode("utf-8")
                    task_meta = json.loads(task_data)
                    state = str(task_meta.get("status") or task_meta.get("state") or "").upper()
                    if state in {"SUCCESS", "FAILURE", "REVOKED"}:
                        return True
            except (TypeError, ValueError, json.JSONDecodeError) as result_exc:
                logger.warning("Unable to parse Celery task result task_id=%s: %s", task_id, result_exc)
                return False
            except Exception as result_exc:
                logger.warning("Unable to read Celery task result task_id=%s: %s", task_id, result_exc)
                return False
            if time.monotonic() >= deadline:
                logger.warning("Timed out waiting for Celery task chain index=%s path=%s task_id=%s", index_name, path_or_url, task_id)
                return False
            time.sleep(max(0.01, float(poll_interval_seconds)))

    @staticmethod
    def delete_lifecycle_record_without_object(
            lifecycle_record: Dict[str, Any],
            requested_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Delete a lifecycle row when no storage object was ever created."""
        file_id = lifecycle_record.get("file_id") if lifecycle_record else None
        object_name = lifecycle_record.get("object_name") if lifecycle_record else None
        if not file_id or object_name:
            raise ValueError("A lifecycle file ID without an object path is required")

        tenant_id = lifecycle_record.get("tenant_id")
        index_name = lifecycle_record.get("index_name")
        current_status = str(lifecycle_record.get("status") or "").upper()
        try:
            get_redis_service().mark_document_delete_requested(
                file_id=file_id,
                requested_by=requested_by,
            )
        except Exception as fence_exc:
            logger.debug("Unable to install no-object deletion fence for %s: %s", file_id, fence_exc)
        try:
            KnowledgeBaseDocumentDeletionService._cancel_document_tasks(
                lifecycle_record=lifecycle_record,
            )
        except Exception as cancel_exc:
            logger.debug("Unable to cancel no-object deletion tasks for %s: %s", file_id, cancel_exc)
        deleteable_statuses = (
            "UPLOADING",
            "UPLOADED",
            "PROCESSING",
            "FORWARDING",
            "FAILED",
            "COMPLETED",
        )

        if current_status == "DELETED":
            delete_file_record(file_id, expected_statuses=("DELETE_REQUESTED", "DELETED"))
            try:
                get_redis_service().clear_document_delete_fence(file_id=file_id)
            except Exception:
                logger.debug("Unable to clear no-object deletion fence for %s", file_id)
            return {
                "status": "success",
                "scope": "full",
                "deleted_es_count": 0,
                "deleted_minio": False,
                "source_available": False,
                "lifecycle_deleted": True,
                "message": "Lifecycle record already deleted; no storage object was created.",
            }

        if current_status != "DELETE_REQUESTED":
            requested = transition_file_record(
                file_id,
                status="DELETE_REQUESTED",
                stage="DELETE",
                expected_statuses=deleteable_statuses,
                updated_by=requested_by,
            )
            if requested is None:
                latest = get_file_record(
                    file_id=file_id,
                    tenant_id=tenant_id,
                    index_name=index_name,
                    include_hidden=True,
                )
                if latest and str(latest.get("status") or "").upper() == "DELETED":
                    current_status = "DELETED"
                elif latest and str(latest.get("status") or "").upper() == "DELETE_REQUESTED":
                    current_status = "DELETE_REQUESTED"
                else:
                    raise ValueError("Lifecycle file record could not be deleted")

        deleted = delete_file_record(
            file_id,
            expected_statuses=("DELETE_REQUESTED", "DELETED"),
        )
        if not deleted:
            latest = get_file_record(
                file_id=file_id,
                tenant_id=tenant_id,
                index_name=index_name,
                include_hidden=True,
            )
            if latest is not None:
                raise ValueError("Lifecycle file record could not be finalized")

        try:
            get_redis_service().clear_document_delete_fence(file_id=file_id)
        except Exception:
            logger.debug("Unable to clear no-object deletion fence for %s", file_id)

        return {
            "status": "success",
            "scope": "full",
            "deleted_es_count": 0,
            "deleted_minio": False,
            "source_available": False,
            "lifecycle_deleted": True,
            "message": "Lifecycle record deleted; no storage object was created.",
        }

    @staticmethod
    async def _finalize_document_delete(
            *, index_name: str, path_or_url: str, scope: str,
            vdb_core: VectorDatabaseCore,
            lifecycle_record: Optional[Dict[str, Any]],
            requested_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Finish a document deletion after its parent chain has stopped."""
        # Resolve the concrete service lazily to avoid the management ->
        # deletion -> service import cycle while still honoring subclass
        # overrides and test doubles.
        from management.services.knowledge_base.service import ElasticSearchService

        service_cls = ElasticSearchService
        file_id = (lifecycle_record or {}).get("file_id")
        legacy_mode = lifecycle_record is None or not lifecycle_record.get("object_name")
        if lifecycle_record and lifecycle_record.get("object_name"):
            drained = await asyncio.to_thread(
                service_cls._wait_for_document_tasks,
                index_name=index_name,
                path_or_url=path_or_url,
                lifecycle_record=lifecycle_record,
                timeout_seconds=DOCUMENT_DELETE_DRAIN_TIMEOUT_S,
            )
            if not drained:
                return {
                    "status": "pending",
                    "scope": scope,
                    "deletion_pending": True,
                    "lifecycle_status": "DELETE_REQUESTED",
                    "source_available": True,
                    "message": "Deletion requested; waiting for Celery tasks to stop.",
                }

        if scope == "source_only":
            try:
                knowledge = get_knowledge_record({"index_name": index_name}) or {}
            except Exception:
                knowledge = {}
            minio_part = service_cls.delete_source_file(
                path_or_url,
                tenant_id=knowledge.get("tenant_id"),
                updated_by=requested_by,
            )
            result = {
                "status": "success" if minio_part.get("deleted_minio") else "failed",
                "scope": scope,
                "deleted_es_count": 0,
                "deleted_minio": bool(minio_part.get("deleted_minio")),
                "source_available": not bool(minio_part.get("deleted_minio")),
                "message": "Source file deleted; index chunks and vectors preserved.",
            }
        else:
            try:
                result = service_cls.delete_documents(index_name, path_or_url, vdb_core)
            except Exception as external_exc:
                logger.warning("External document cleanup failed index=%s path=%s: %s", index_name, path_or_url, external_exc)
                return {
                    "status": "pending",
                    "scope": scope,
                    "deletion_pending": True,
                    "lifecycle_status": "DELETE_REQUESTED",
                    "source_available": True,
                    "external_delete_error": str(external_exc),
                    "message": "Deletion requested; external cleanup will be retried.",
                }
            result["scope"] = scope
            result["source_available"] = not result.get("deleted_minio", False)

        if scope == "full":
            try:
                redis_cleanup = get_redis_service().delete_document_records(index_name, path_or_url)
                result["redis_cleanup"] = redis_cleanup
                if redis_cleanup.get("errors") and not legacy_mode:
                    return {
                        **result,
                        "status": "pending",
                        "deletion_pending": True,
                        "lifecycle_status": "DELETE_REQUESTED",
                        "redis_warnings": redis_cleanup["errors"],
                        "message": "External data deleted; waiting for Redis task cleanup.",
                    }
            except Exception as redis_exc:
                logger.warning("Redis document cleanup failed index=%s path=%s: %s", index_name, path_or_url, redis_exc)
                if not legacy_mode:
                    return {
                        **result,
                        "status": "pending",
                        "deletion_pending": True,
                        "lifecycle_status": "DELETE_REQUESTED",
                        "redis_cleanup_error": str(redis_exc),
                        "message": "External data deleted; waiting for Redis task cleanup.",
                    }

        try:
            if file_id and not legacy_mode:
                delete_file_record(file_id, expected_statuses=("DELETE_REQUESTED", "DELETED"))
            else:
                if requested_by is None:
                    service_cls._mark_file_deleted(index_name, path_or_url)
                else:
                    service_cls._mark_file_deleted(
                        index_name, path_or_url, updated_by=requested_by
                    )
        except Exception as lifecycle_exc:
            logger.warning("Lifecycle hard delete failed index=%s path=%s file_id=%s: %s", index_name, path_or_url, file_id, lifecycle_exc)
            return {
                **result,
                "status": "pending",
                "deletion_pending": True,
                "lifecycle_status": "DELETE_REQUESTED",
                "lifecycle_delete_error": str(lifecycle_exc),
                "message": "External data deleted; waiting for lifecycle cleanup.",
            }

        try:
            fence_service = get_redis_service()
            fence_service.clear_document_delete_fence(file_id=file_id)
            if file_id and not legacy_mode and fence_service.is_document_delete_requested(file_id=file_id):
                return {
                    **result,
                    "status": "pending",
                    "deletion_pending": True,
                    "lifecycle_status": "DELETE_REQUESTED",
                    "message": "External data deleted; waiting for deletion fence cleanup.",
                }
        except Exception as fence_exc:
            logger.warning("Failed to clear deletion fence index=%s path=%s: %s", index_name, path_or_url, fence_exc)
            if not legacy_mode:
                return {
                    **result,
                    "status": "pending",
                    "deletion_pending": True,
                    "lifecycle_status": "DELETE_REQUESTED",
                    "fence_cleanup_error": str(fence_exc),
                    "message": "External data deleted; waiting for deletion fence cleanup.",
                }
        result["lifecycle_deleted"] = True
        return result

    @staticmethod
    async def _retry_document_delete(
            *, index_name: str, path_or_url: str, scope: str,
            vdb_core: VectorDatabaseCore,
            lifecycle_record: Optional[Dict[str, Any]],
            requested_by: Optional[str] = None,
    ) -> None:
        from management.services.knowledge_base.service import ElasticSearchService

        file_id = (lifecycle_record or {}).get("file_id") or path_or_url
        try:
            while True:
                try:
                    result = await ElasticSearchService._finalize_document_delete(
                        index_name=index_name,
                        path_or_url=path_or_url,
                        scope=scope,
                        vdb_core=vdb_core,
                        lifecycle_record=lifecycle_record,
                        requested_by=requested_by,
                    )
                    if result.get("status") != "pending":
                        return
                except Exception as exc:
                    logger.warning("Background deletion finalizer failed index=%s path=%s: %s", index_name, path_or_url, exc)
                await asyncio.sleep(max(0.2, DOCUMENT_DELETE_RETRY_INTERVAL_S))
        except asyncio.CancelledError:
            raise
        finally:
            _document_delete_tasks.pop(str(file_id), None)

    @staticmethod
    def _schedule_document_delete_retry(
            *, index_name: str, path_or_url: str, scope: str,
            vdb_core: VectorDatabaseCore,
            lifecycle_record: Optional[Dict[str, Any]],
            requested_by: Optional[str] = None,
    ) -> None:
        from management.services.knowledge_base.service import ElasticSearchService

        key = str((lifecycle_record or {}).get("file_id") or path_or_url)
        existing = _document_delete_tasks.get(key)
        if existing and not existing.done():
            return
        _document_delete_tasks[key] = asyncio.create_task(
            ElasticSearchService._retry_document_delete(
                index_name=index_name,
                path_or_url=path_or_url,
                scope=scope,
                vdb_core=vdb_core,
                lifecycle_record=lifecycle_record,
                requested_by=requested_by,
            )
        )

    @staticmethod
    async def delete_document_by_scope(
            index_name: str,
            path_or_url: str,
            scope: str,
            vdb_core: VectorDatabaseCore,
            file_id: Optional[str] = None,
            requested_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        from management.services.knowledge_base.service import ElasticSearchService

        service_cls = ElasticSearchService
        if scope not in KnowledgeBaseDocumentDeletionService.DOCUMENT_DELETE_SCOPES:
            raise ValueError(
                f"Invalid scope '{scope}'. "
                f"Must be one of: {KnowledgeBaseDocumentDeletionService.DOCUMENT_DELETE_SCOPES}"
            )

        if scope == "source_only":
            await service_cls._assert_source_only_deletable(
                index_name, path_or_url
            )
        if file_id is None and requested_by is None:
            lifecycle_record = service_cls._mark_file_delete_requested(
                index_name, path_or_url
            )
        else:
            lifecycle_record = service_cls._mark_file_delete_requested(
                index_name,
                path_or_url,
                requested_by=requested_by,
                file_id=file_id,
            )
        cancellation = service_cls._cancel_document_tasks(
            lifecycle_record=lifecycle_record,
        )
        result = await service_cls._finalize_document_delete(
            index_name=index_name,
            path_or_url=path_or_url,
            scope=scope,
            vdb_core=vdb_core,
            lifecycle_record=lifecycle_record,
            requested_by=requested_by,
        )
        result["cancelled_tasks"] = cancellation
        if result.get("status") == "pending":
            service_cls._schedule_document_delete_retry(
                index_name=index_name,
                path_or_url=path_or_url,
                scope=scope,
                vdb_core=vdb_core,
                lifecycle_record=lifecycle_record,
                requested_by=requested_by,
            )
        return result

    @staticmethod
    def delete_documents(
            index_name: str = Path(..., description="Name of the index"),
            path_or_url: str = Query(...,
                                     description="Path or URL of documents to delete"),
            vdb_core: VectorDatabaseCore = Depends(get_vector_db_core)
    ):
        # 1. Delete ES documents
        deleted_count = vdb_core.delete_documents(
            index_name, path_or_url)
        # 2. Delete MinIO file
        minio_result = delete_file(path_or_url)
        if minio_result.get("success"):
            try:
                knowledge = get_knowledge_record({"index_name": index_name}) or {}
                tenant_id = knowledge.get("tenant_id")
                reference = resolve_storage_reference(path_or_url)
                if tenant_id and reference:
                    release_storage_charge(
                        tenant_id=tenant_id,
                        bucket_name=reference.bucket_name,
                        object_name=reference.object_name,
                    )
            except Exception:
                logger.exception(
                    "Failed to reconcile storage ledger after deleting '%s'",
                    path_or_url,
                )

        # Update last_doc_update_time for auto-summary tracking
        update_last_doc_update_time(index_name)

        return {"status": "success", "deleted_es_count": deleted_count, "deleted_minio": minio_result.get("success")}
