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
from typing import Any, Dict, Optional

from fastapi import Depends, Path, Query
from nexent.vector_database.base import VectorDatabaseCore

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
from utils.file_management_utils import get_all_files_status



from management.services.knowledge_base.common import (
    get_vector_db_core,
    logger,
)
from management.services.knowledge_base.management import KnowledgeBaseManagementService



class KnowledgeBaseDocumentDeletionService(KnowledgeBaseManagementService):
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
    ) -> Optional[Dict[str, Any]]:
        """Hide a file from list results before deleting external data."""
        try:
            knowledge = get_knowledge_record({"index_name": index_name}) or {}
            tenant_id = knowledge.get("tenant_id")
            knowledge_id = knowledge.get("knowledge_id")
            if tenant_id is None or knowledge_id is None:
                return None
            record = get_file_record(
                tenant_id=tenant_id,
                index_name=index_name,
                object_name=path_or_url,
                include_hidden=True,
            )
            if record:
                return transition_file_record(
                    record["file_id"],
                    status="DELETE_REQUESTED",
                    stage="DELETE",
                    updated_by=requested_by,
                ) or record
            return create_delete_tombstone(
                tenant_id=str(tenant_id),
                knowledge_id=int(knowledge_id),
                index_name=index_name,
                object_name=path_or_url,
                requested_by=requested_by,
            )
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
            updated_by: Optional[str] = None,
    ) -> None:
        try:
            knowledge = get_knowledge_record({"index_name": index_name}) or {}
            record = get_file_record(
                tenant_id=knowledge.get("tenant_id"),
                index_name=index_name,
                object_name=path_or_url,
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
    async def delete_document_by_scope(
            index_name: str,
            path_or_url: str,
            scope: str,
            vdb_core: VectorDatabaseCore,
    ) -> Dict[str, Any]:
        if scope not in KnowledgeBaseDocumentDeletionService.DOCUMENT_DELETE_SCOPES:
            raise ValueError(
                f"Invalid scope '{scope}'. "
                f"Must be one of: {KnowledgeBaseDocumentDeletionService.DOCUMENT_DELETE_SCOPES}"
            )

        if scope == "source_only":
            await KnowledgeBaseDocumentDeletionService._assert_source_only_deletable(
                index_name, path_or_url
            )
            KnowledgeBaseDocumentDeletionService._mark_file_delete_requested(index_name, path_or_url)
            try:
                knowledge = get_knowledge_record({"index_name": index_name}) or {}
            except Exception:
                logger.exception(
                    "Failed to resolve storage ownership for index '%s'",
                    index_name,
                )
                knowledge = {}
            minio_part = KnowledgeBaseDocumentDeletionService.delete_source_file(
                path_or_url,
                tenant_id=knowledge.get("tenant_id"),
            )
            deleted_minio = minio_part.get("deleted_minio", False)
            KnowledgeBaseDocumentDeletionService._mark_file_deleted(index_name, path_or_url)
            return {
                "status": "success" if deleted_minio else "failed",
                "scope": scope,
                "deleted_es_count": 0,
                "deleted_minio": deleted_minio,
                "source_available": not deleted_minio,
                "message": (
                    "Source file deleted; index chunks and vectors preserved."
                    if deleted_minio
                    else "Source file deletion failed; index chunks and vectors preserved."
                ),
            }

        KnowledgeBaseDocumentDeletionService._mark_file_delete_requested(index_name, path_or_url)
        result = KnowledgeBaseDocumentDeletionService.delete_documents(
            index_name, path_or_url, vdb_core
        )
        KnowledgeBaseDocumentDeletionService._mark_file_deleted(index_name, path_or_url)
        result["scope"] = scope
        result["source_available"] = not result.get("deleted_minio", False)
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
