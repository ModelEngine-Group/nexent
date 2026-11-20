# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from contracts.file_types import get_content_type
from infrastructure.system_configuration.runtime import get_config_snapshot
import logging
import os
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from time import monotonic
from uuid import uuid4
from typing import Dict, List, Optional, Tuple

import httpx
from contracts.constants.constants import (
    ASSET_OWNER_ATTACHMENTS_PREFIX,
    ASSET_OWNER_TENANT_ID,
    MODEL_CONFIG_MAPPING,
)
from contracts.constants.environment import MAX_KNOWLEDGE_FILE_SIZE_BYTES, UPLOAD_FOLDER
from contracts.object_tickets import InvalidObjectTicket, issue_download_url
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import (
    AppException,
    FileTooLargeException,
)
from contracts.errors.ingestion import ingestion_error_fields
from fastapi import UploadFile
from management.db.file.attachment import (
    generate_object_name,
    upload_fileobj,
)
from management.db.model.repository import get_model_by_model_id
from management.services.configuration.tenant.settings import tenant_config_manager
from management.services.file.source_upload import upload_knowledge_source
from management.services.file.upload_admission import admit_knowledge_uploads, update_upload_record
from management.services.file.upload_context import resolve_upload_context
from management.services.knowledge_base.usage_cache import invalidate_usage_cache
from management.services.model.names import get_model_name_from_config
from nexent import MessageObserver
from nexent.core.concurrency import run_blocking
from nexent.core.models import OpenAILongContextModel
from nexent.multi_modal.utils import parse_s3_url
from nexent.storage.errors import OutcomeUnknown, ScopeDenied, StorageError
from nexent.storage.models import OperationContext

from infrastructure.attachment_inventory import attachment_inventory_port
from infrastructure.trace.knowledge import trace_knowledge_operation

# Create upload directory
upload_dir = Path(UPLOAD_FOLDER)
upload_dir.mkdir(exist_ok=True)

# Per-file locks prevent duplicate conversions of the same file

logger = logging.getLogger("file_management_service")

ALLOWED_SKILL_UPLOAD_ROOT = Path("/mnt/nexent").resolve()


def is_allowed_skill_upload_path(file_path: str) -> bool:
    """Return True when a local file path is under the allowed skill upload root."""
    if not file_path:
        return False

    try:
        candidate_path = Path(file_path).resolve()
    except Exception:
        return False

    try:
        candidate_path.relative_to(ALLOWED_SKILL_UPLOAD_ROOT)
        return True
    except ValueError:
        return False




def resolve_minio_upload_folder(
    folder: Optional[str],
    user_id: Optional[str] = None,
    uploader_tenant_id: Optional[str] = None,
) -> str:
    """Map caller context to the MinIO object prefix used for uploads.

    Resolution order (first match wins):
    1. Asset-owner tenant → ``attachments/asset_owner/{user_id}``
    2. ``folder == "knowledge_base"`` → shared ``knowledge_base`` prefix
    3. Otherwise → per-user ``attachments/{user_id}`` when ``user_id`` is set
    4. Legacy fallback → ``folder`` if provided, else ``attachments``

    Access control for reads is enforced separately; this function only
    chooses the storage prefix.

    Args:
        folder: Requested folder hint (e.g. ``"knowledge_base"`` or a legacy path).
        user_id: Uploader user ID; required for user-scoped attachment paths.
        uploader_tenant_id: Uploader tenant ID; asset-owner tenants use a dedicated prefix.

    Returns:
        Resolved MinIO folder prefix (no leading or trailing slash).
    """
    if uploader_tenant_id == ASSET_OWNER_TENANT_ID:
        return f"{ASSET_OWNER_ATTACHMENTS_PREFIX}/{user_id}"

    if folder == "knowledge_base":
        return "knowledge_base"

    if folder == "skill-files":
        if user_id:
            return f"skill-files/{user_id}"
        return "skill-files"

    if user_id:
        return f"attachments/{user_id}"

    return folder or "attachments"










from contracts.file import UploadFilesResult


async def _get_complete_upload_batch_size(files: List[UploadFile]) -> int:
    """Return the full raw batch size without changing upload stream positions."""
    total_size = 0
    for upload in files:
        if not upload:
            continue

        declared_size = getattr(upload, "size", None)
        if (
            isinstance(declared_size, int)
            and not isinstance(declared_size, bool)
            and declared_size > 0
        ):
            total_size += declared_size
            continue

        file_object = getattr(upload, "file", None)
        if file_object is not None:
            original_position = None
            try:
                original_position = file_object.tell()
                file_object.seek(0, os.SEEK_END)
                measured_size = file_object.tell()
                if isinstance(measured_size, int) and measured_size >= 0:
                    total_size += measured_size
                    continue
            except (AttributeError, OSError, TypeError, ValueError):
                pass
            finally:
                if original_position is not None:
                    try:
                        file_object.seek(original_position)
                    except (AttributeError, OSError, TypeError, ValueError):
                        logger.warning("Failed to restore upload file position")

        try:
            await upload.seek(0)
            content = await upload.read()
            total_size += len(content)
        finally:
            await upload.seek(0)
    return total_size


async def _get_upload_size(upload: UploadFile) -> int:
    """Return one upload's size without changing its stream position."""
    declared_size = getattr(upload, "size", None)
    if isinstance(declared_size, int) and not isinstance(declared_size, bool) and declared_size > 0:
        return declared_size

    file_object = getattr(upload, "file", None)
    if file_object is not None:
        original_position = None
        try:
            original_position = file_object.tell()
            file_object.seek(0, os.SEEK_END)
            measured_size = file_object.tell()
            if isinstance(measured_size, int) and measured_size >= 0:
                return measured_size
        except (AttributeError, OSError, TypeError, ValueError):
            pass
        finally:
            if original_position is not None:
                try:
                    file_object.seek(original_position)
                except (AttributeError, OSError, TypeError, ValueError):
                    logger.warning("Failed to restore upload file position")

    await upload.seek(0)
    try:
        content = await upload.read()
        return len(content)
    finally:
        await upload.seek(0)


def _is_knowledge_base_upload(folder: Optional[str], index_name: Optional[str]) -> bool:
    """Identify uploads that belong to the local knowledge-base document flow."""
    # The browser path uses the explicit knowledge_base folder. Northbound
    # uploads omit the folder but always provide an index_name. Other callers
    # may use an index_name for filename conflict resolution in an arbitrary
    # storage folder, which must not inherit the KB document-size policy.
    return folder == "knowledge_base" or (folder is None and bool(index_name))


async def _validate_knowledge_file_sizes(
    files: List[UploadFile],
) -> None:
    """Reject oversized KB documents before any file is written to storage."""
    limit_mb = get_config_snapshot().get("MAX_KNOWLEDGE_FILE_SIZE_MB")
    limit_bytes = limit_mb * 1024 * 1024
    for upload in files:
        if not upload:
            continue
        file_size = await _get_upload_size(upload)
        if file_size <= limit_bytes:
            continue

        filename = upload.filename or "unknown"
        raise AppException(
            ErrorCode.FILE_TOO_LARGE,
            f"Knowledge base file '{filename}' exceeds the {limit_mb} MB limit",
            details={
                "resource": "knowledge_file",
                "limit_bytes": limit_bytes,
                "limit_mb": limit_mb,
                "file_name": filename,
                "actual_bytes": file_size,
            },
        )


async def upload_files_impl(
    destination: str,
    file: List[UploadFile],
    folder: str = None,
    index_name: Optional[str] = None,
    user_id: Optional[str] = None,
    uploader_tenant_id: Optional[str] = None,
    upload_owner_service: Optional[str] = None,
    lifecycle_file_ids: list[str] | None = None,
) -> tuple:
    """
    Upload files to local storage or MinIO based on destination.

    Args:
        destination: "local" or "minio"
        file: List of UploadFile objects
        folder: Folder name for MinIO uploads
        index_name: Knowledge base index for conflict resolution
        user_id: User ID for attachment path isolation
        uploader_tenant_id: Uploader tenant ID (ASSET_OWNER uses dedicated prefix)
        upload_owner_service: Service responsible for recovering interrupted uploads
        lifecycle_file_ids: Trusted preallocated IDs for an already reserved local binding

    Returns:
        UploadFilesResult: Three-item tuple-compatible result with quota metadata
    """
    uploaded_filenames = []
    uploaded_file_paths = []
    errors = []
    quota_status = None
    lifecycle_records = []
    if not file:
        return UploadFilesResult([], [], [])
    if destination == "local" and index_name:
        await _validate_knowledge_file_sizes(file)
        from functools import partial

        from management.services.file.local_knowledge_source import (
            upload_local_knowledge_files,
        )

        from infrastructure.agentos_identity import ServicePrincipal

        return await upload_local_knowledge_files(
            file, actor=ServicePrincipal(user_id, uploader_tenant_id), root=upload_dir,
            uploader=partial(upload_files_impl, destination="minio", folder=folder, index_name=index_name,
                             user_id=user_id, uploader_tenant_id=uploader_tenant_id, upload_owner_service=upload_owner_service),
        )
    if destination == "local":
        if _is_knowledge_base_upload(folder, index_name):
            await _validate_knowledge_file_sizes(file)
        from management.services.file.staged_local_source import (
            upload_staged_local_files,
        )

        from infrastructure.agentos_identity import ServicePrincipal

        return await upload_staged_local_files(file, ServicePrincipal(user_id, uploader_tenant_id), upload_dir)

    elif destination == "minio":
        if _is_knowledge_base_upload(folder, index_name):
            await _validate_knowledge_file_sizes(file)
        actual_folder = resolve_minio_upload_folder(
            folder, user_id, uploader_tenant_id)

        from infrastructure.agentos_identity import ServicePrincipal

        actor = ServicePrincipal(user_id, uploader_tenant_id) if index_name and uploader_tenant_id else None
        storage_context = await resolve_upload_context(index_name, actor) if actor else None
        if index_name and _is_knowledge_base_upload(folder, index_name) and storage_context is None:
            raise ScopeDenied()
        if lifecycle_file_ids is not None:
            import re

            if (not storage_context or len(lifecycle_file_ids) != len(file)
                    or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value) for value in lifecycle_file_ids)
                    or len(set(lifecycle_file_ids)) != len(lifecycle_file_ids)):
                from nexent.storage.errors import InvalidInput

                raise InvalidInput()
        lifecycle_records_by_index = {}
        if storage_context:
            lifecycle_record_indices = []
            lifecycle_record_specs = []
            for file_index, upload in enumerate(file):
                if not upload:
                    continue
                original_filename = os.path.basename(upload.filename or "")
                planned_object_name = generate_object_name(
                    original_filename, prefix=actual_folder)
                lifecycle_record_indices.append(file_index)
                lifecycle_record_specs.append({
                    **({"file_id": lifecycle_file_ids[file_index]} if lifecycle_file_ids is not None else {}),
                    "tenant_id": storage_context.tenant_id,
                    "knowledge_id": storage_context.knowledge_id,
                    "index_name": storage_context.index_name,
                    "original_filename": original_filename,
                    "bucket_name": storage_context.bucket_name,
                    "object_name": planned_object_name,
                    "file_size": getattr(upload, "size", None),
                    "upload_owner_service": upload_owner_service,
                    "status": "UPLOADING",
                    "stage": "UPLOAD",
                    "created_by": user_id,
                })

            if lifecycle_record_specs:
                # Lifecycle persistence is a required upload precondition. The
                # repository creates the whole batch in one transaction; any
                # database error must stop before MinIO is touched.
                from infrastructure.agentos_identity import ServicePrincipal

                lifecycle_records = await admit_knowledge_uploads(
                    lifecycle_record_specs, actor=actor,
                )
                if len(lifecycle_records) != len(lifecycle_record_indices):
                    raise RuntimeError("Lifecycle record batch creation returned an incomplete result")
                lifecycle_records_by_index = dict(
                    zip(lifecycle_record_indices, lifecycle_records))
        quota_service = None
        if storage_context:
            from management.services.file.upload_quota import UploadQuota

            total_file_size = await _get_complete_upload_batch_size(file)
            quota_service = UploadQuota(actor, storage_context)
            try:
                quota_status = await quota_service.before(total_file_size)
            except Exception as quota_exc:
                error_fields = ingestion_error_fields(quota_exc, "QUOTA")
                for record in lifecycle_records_by_index.values():
                    await update_upload_record(
                        record["file_id"],
                        status="FAILED",
                        stage="QUOTA",
                        **error_fields,
                        error_stage="QUOTA",
                        expected_statuses=("UPLOADING",),
                        failed_at=datetime.now(timezone.utc).isoformat(),
                        actor=actor,
                    )
                raise

        if lifecycle_records_by_index:
            minio_results = await upload_to_minio(
                files=file,
                folder=actual_folder,
                file_records=lifecycle_records_by_index,
            )
        else:
            minio_results = await upload_to_minio(files=file, folder=actual_folder)
        successful_lifecycle_records = []
        for file_index, result in enumerate(minio_results):
            record = lifecycle_records_by_index.get(file_index)
            file_id = (record or {}).get("file_id")
            if result.get("success"):
                if file_id:
                    updated_record = await update_upload_record(
                        file_id,
                        status="UPLOADED",
                        stage="UPLOAD",
                        object_name=result.get("object_name"),
                        file_size=result.get("file_size"),
                        uploaded_at=datetime.now(timezone.utc).isoformat(),
                        expected_statuses=("UPLOADING",),
                        actor=actor,
                    )
                    if updated_record:
                        lifecycle_records_by_index[file_index] = updated_record
                        record = updated_record
                    elif not record or record.get("status") != "UPLOADED":
                        errors.append(
                            f"Failed to upload {result.get('file_name')}: "
                            "Upload state changed before completion"
                        )
                        continue
                    if record and file_id:
                        # ``uploaded_filenames`` only contains successful uploads. Keep
                        # the corresponding lifecycle records in the same success order
                        # so a partial batch cannot update the wrong file name.
                        successful_lifecycle_records.append(record)
                uploaded_filenames.append(result.get("file_name"))
                uploaded_file_paths.append(result.get("object_name"))
            else:
                file_name = result.get('file_name')
                error_msg = result.get('error', 'Unknown error')
                errors.append(f"Failed to upload {file_name}: {error_msg}")
                if file_id and not result.get("outcome_unknown"):
                    error_fields = ingestion_error_fields(result, "UPLOAD")
                    updated_record = await update_upload_record(
                        file_id,
                        status="FAILED",
                        stage="UPLOAD",
                        **error_fields,
                        error_stage="UPLOAD",
                        failed_at=datetime.now(timezone.utc).isoformat(),
                        expected_statuses=("UPLOADING",),
                        actor=actor,
                    )
                    if updated_record:
                        lifecycle_records_by_index[file_index] = updated_record

        # Resolve filename conflicts against existing KB documents by renaming (e.g., name -> name_1)
        if index_name:
            try:
                from management.services.knowledge_base.file_listing import (
                    list_knowledge_files,
                )

                from infrastructure.agentos_identity import ServicePrincipal

                existing = await list_knowledge_files(index_name, ServicePrincipal(user_id, uploader_tenant_id))
                existing_files = existing.get(
                    "files", []) if isinstance(existing, dict) else []
                # list_files merges durable lifecycle rows, including this
                # batch's own -- exclude them or every first upload renames
                # itself to <name>_1 (only merged rows carry a file_id).
                own_file_ids = {r["file_id"] for r in lifecycle_records if r.get("file_id")}
                existing_names = set()
                for item in existing_files:
                    if item.get("file_id") in own_file_ids:
                        continue
                    name = (item.get("file") or item.get(
                        "filename") or "").strip()
                    if name:
                        existing_names.add(name.lower())

                def make_unique_names(original_names: List[str], taken_lower: set) -> List[str]:
                    unique_list: List[str] = []
                    local_taken = set(taken_lower)
                    for original in original_names:
                        base, ext = os.path.splitext(original or "")
                        candidate = original or ""
                        if not candidate:
                            unique_list.append(candidate)
                            continue
                        suffix = 1
                        # Ensure case-insensitive uniqueness
                        while candidate.lower() in local_taken:
                            candidate = f"{base}_{suffix}{ext}"
                            suffix += 1
                        unique_list.append(candidate)
                        local_taken.add(candidate.lower())
                    return unique_list

                uploaded_filenames[:] = make_unique_names(
                    uploaded_filenames, existing_names)

                # The legacy UI and task metadata use the conflict-resolved name. The
                # lifecycle row is created before this resolution, so synchronize its
                # existing filename column after resolving names. Historical rows are
                # intentionally not modified; only the current upload batch is updated.
                for record, effective_filename in zip(successful_lifecycle_records, uploaded_filenames):
                    current_filename = record.get("original_filename")
                    if not record.get("file_id") or current_filename is None or current_filename == effective_filename:
                        continue
                    try:
                        updated_record = await update_upload_record(
                            record["file_id"],
                            original_filename=effective_filename,
                            expected_statuses=("UPLOADED",),
                            actor=actor,
                        )
                        if updated_record:
                            record.update(updated_record)
                    except Exception as filename_exc:
                        # MinIO and the upload response are already successful. Do not
                        # turn a best-effort name synchronization failure into a second
                        # upload failure; the task/ES name remains the legacy fallback.
                        logger.warning(
                            "Failed to synchronize lifecycle filename for file_id=%s: %s",
                            record["file_id"],
                            filename_exc,
                        )
            except Exception as e:
                logger.warning(
                    f"Failed to resolve filename conflicts for index '{index_name}': {str(e)}")

        if storage_context and uploaded_file_paths:
            from management.services.file.object_deletion import (
                compensate_uploaded_objects,
            )

            try:
                invalidate_usage_cache(storage_context.tenant_id)
                quota_status = await quota_service.after()
            except Exception as exc:
                error_fields = ingestion_error_fields(exc, "STORAGE_COMMIT")
                for record in lifecycle_records_by_index.values():
                    if record.get("status") in {"UPLOADING", "UPLOADED"}:
                        await update_upload_record(
                            record["file_id"],
                            status="FAILED",
                            stage="STORAGE_COMMIT",
                            **error_fields,
                            error_stage="STORAGE_COMMIT",
                            failed_at=datetime.now(timezone.utc).isoformat(),
                            expected_statuses=("UPLOADING", "UPLOADED"),
                            actor=actor,
                        )
                await compensate_uploaded_objects(storage_context, uploaded_file_paths,
                    actor)
                invalidate_usage_cache(storage_context.tenant_id)
                raise
    else:
        raise Exception("Invalid destination. Must be 'local' or 'minio'.")

    return UploadFilesResult(
        errors,
        uploaded_file_paths,
        uploaded_filenames,
        quota_status,
        list(lifecycle_records_by_index.values()) if destination == "minio" else lifecycle_records,
    )


@trace_knowledge_operation("knowledge.upload.batch", "upload")
async def upload_to_minio(
    files: List[UploadFile],
    folder: str,
    user_id: Optional[str] = None,
    uploader_tenant_id: Optional[str] = None,
    file_records: Optional[dict] = None,
) -> List[dict]:
    """
    Helper function to upload files to MinIO and return results.

    Args:
        files: List of files to upload
        folder: Storage folder path or resolved MinIO prefix
        user_id: User ID for attachment path isolation when folder is generic
        uploader_tenant_id: Uploader tenant ID for ASSET_OWNER attachment prefix

    Returns:
        List of upload results
    """
    actual_folder = resolve_minio_upload_folder(
        folder, user_id, uploader_tenant_id)
    results = []
    for file_index, f in enumerate(files):
        lifecycle_record = (file_records or {}).get(file_index)
        try:
            # Read file content
            file_content = await f.read()

            # Store original filename before upload
            original_filename = f.filename or ""

            if lifecycle_record:
                content_type = get_content_type(original_filename)
                await upload_knowledge_source(lifecycle_record, file_content, content_type)
                result = {
                    "success": True, "file_name": original_filename,
                    "object_name": lifecycle_record["object_name"], "file_size": len(file_content),
                    "content_type": content_type,
                    "upload_time": datetime.now().isoformat(),  # noqa: DTZ005 - Preserve the existing result format.
                    "url": f"/{lifecycle_record['bucket_name']}/{lifecycle_record['object_name']}",
                }
            else:
                result = await run_blocking(
                    "attachment-upload", upload_fileobj, file_obj=BytesIO(file_content), file_name=original_filename,
                    prefix=actual_folder, file_size=len(file_content), lane="file-upload", owner="management.file",
                )

            # Preserve original filename in result (upload_fileobj uses it for object name generation)
            result["original_file_name"] = original_filename
            if lifecycle_record:
                result["file_id"] = lifecycle_record.get("file_id")

            # Reset file pointer for potential re-reading
            await f.seek(0)
            results.append(result)

        except OutcomeUnknown:
            logger.warning("knowledge_source_upload_outcome_unknown file_id=%s", (lifecycle_record or {}).get("file_id"))
            results.append({
                "success": False, "file_name": f.filename, "original_file_name": f.filename,
                "file_id": (lifecycle_record or {}).get("file_id"), "outcome_unknown": True,
                "error_code": "SOURCE_UPLOAD_OUTCOME_UNKNOWN", "error": "Source upload requires reconciliation",
            })
        except Exception as e:
            # Log single file upload failure but continue processing other files
            logger.error(
                f"Failed to upload file {f.filename}: {e}", exc_info=True)
            results.append({
                "success": False,
                "file_name": f.filename,
                "original_file_name": f.filename,
                "file_id": (lifecycle_record or {}).get("file_id"),
                "error": str(e)[:500] or "An error occurred while processing the file."
            })
    return results


async def get_file_url_impl(object_name: str, expires: int):
    try:
        url = issue_download_url(object_name, expires)
    except InvalidObjectTicket:
        raise RuntimeError("File does not exist or cannot be accessed: Download link unavailable") from None
    return {"success": True, "object_name": object_name, "expires_in": expires,
            "url": url}


def _list_attachment_files(prefix: str, limit: int | None) -> list[dict]:
    context = OperationContext(f'attachment-list-{uuid4().hex}', monotonic() + 5)
    try:
        inventory = attachment_inventory_port()
        try:
            entries = inventory.first_page(prefix, limit=1000, context=context)
        finally:
            inventory.close()
    except StorageError as error:
        logger.warning("attachment_list_unavailable operation_id=%s error_type=%s",
                       context.operation_id, type(error).__name__)
        return []
    items = []
    for entry in entries[:limit] if limit else entries:
        row = {
            "key": entry.key, "size": entry.size, "last_modified": entry.last_modified,
            "content_type": get_content_type(entry.key),
        }
        items.append(row)
    return items


async def list_files_impl(prefix: str, limit: Optional[int] = None):
    return await run_blocking(
        "attachment-list", _list_attachment_files, prefix, limit, lane="control-io", owner="management.file",
    )











from management.services.file.access import (
    check_file_access,
    check_file_access_batch,
    validate_s3_url_access,
    validate_urls_access,
)
from management.services.model.media import (
    get_llm_model,
)
