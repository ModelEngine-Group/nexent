# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
import logging

from management.services.file.preview import build_preview_pdf_object_key
import os
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx
from fastapi import UploadFile
from nexent import MessageObserver
from nexent.core.concurrency import run_blocking
from nexent.core.models import OpenAILongContextModel
from nexent.multi_modal.utils import parse_s3_url

from contracts.constants.identity import ASSET_OWNER_ATTACHMENTS_PREFIX, ASSET_OWNER_TENANT_ID
from consts.const import DATA_PROCESS_SERVICE, MAX_KNOWLEDGE_FILE_SIZE_BYTES, UPLOAD_FOLDER
from contracts.constants.file import FILE_PREVIEW_SIZE_LIMIT, MAX_CONCURRENT_UPLOADS, OFFICE_MIME_TYPES
from contracts.constants.model import MODEL_CONFIG_MAPPING
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException, FileTooLargeException, NotFoundException, OfficeConversionException, UnsupportedFileTypeException
from management.db.file.attachment import copy_file, delete_file, file_exists, generate_object_name, get_content_type, get_file_range, get_file_size_from_minio, get_file_stream, get_file_stream_raw, get_file_url, list_files, upload_fileobj
from management.db.knowledge_base.file_lifecycle import create_file_records, transition_file_record
from management.db.model.repository import get_model_by_model_id
from management.services.knowledge_base.service import ElasticSearchService, get_vector_db_core
from management.services.configuration.tenant.settings import tenant_config_manager
from management.services.model.names import get_model_name_from_config
from management.services.file.upload import save_upload_file
from infrastructure.ingestion.errors import ingestion_error_fields
from infrastructure.observability.knowledge import trace_knowledge_operation


# Create upload directory
upload_dir = Path(UPLOAD_FOLDER)
upload_dir.mkdir(exist_ok=True)
upload_semaphore = asyncio.Semaphore(MAX_CONCURRENT_UPLOADS)

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
    for upload in files:
        if not upload:
            continue
        file_size = await _get_upload_size(upload)
        if file_size <= MAX_KNOWLEDGE_FILE_SIZE_BYTES:
            continue

        filename = upload.filename or "unknown"
        limit_mb = MAX_KNOWLEDGE_FILE_SIZE_BYTES // (1024 * 1024)
        raise AppException(
            ErrorCode.FILE_TOO_LARGE,
            f"Knowledge base file '{filename}' exceeds the {limit_mb} MB limit",
            details={
                "resource": "knowledge_file",
                "limit_bytes": MAX_KNOWLEDGE_FILE_SIZE_BYTES,
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

    Returns:
        UploadFilesResult: Three-item tuple-compatible result with quota metadata
    """
    uploaded_filenames = []
    uploaded_file_paths = []
    errors = []
    quota_status = None
    lifecycle_records = []
    if destination == "local":
        if _is_knowledge_base_upload(folder, index_name):
            await _validate_knowledge_file_sizes(file)
        async with upload_semaphore:
            for f in file:
                if not f:
                    continue

                safe_filename = os.path.basename(f.filename or "")
                upload_path = upload_dir / safe_filename
                absolute_path = upload_path.absolute()

                # Save file
                if await save_upload_file(f, upload_path):
                    uploaded_filenames.append(safe_filename)
                    uploaded_file_paths.append(str(absolute_path))
                    logger.info(f"Successfully saved file: {safe_filename}")
                else:
                    errors.append(f"Failed to save file: {f.filename}")

    elif destination == "minio":
        if _is_knowledge_base_upload(folder, index_name):
            await _validate_knowledge_file_sizes(file)
        actual_folder = resolve_minio_upload_folder(
            folder, user_id, uploader_tenant_id)

        from management.services.knowledge_base.storage import resolve_storage_context

        storage_context = resolve_storage_context(index_name, uploader_tenant_id)
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
                lifecycle_records = create_file_records(lifecycle_record_specs)
                if len(lifecycle_records) != len(lifecycle_record_indices):
                    raise RuntimeError("Lifecycle record batch creation returned an incomplete result")
                lifecycle_records_by_index = dict(
                    zip(lifecycle_record_indices, lifecycle_records))
        quota_service = None
        if storage_context:
            from management.services.knowledge_base.quota import QuotaService

            total_file_size = await _get_complete_upload_batch_size(file)
            quota_service = QuotaService(storage_context.tenant_id, user_id)
            try:
                quota_status = quota_service.check_hard_limit(
                    total_file_size,
                    index_name=storage_context.index_name,
                )
                if (
                    getattr(storage_context, "ingroup_permission", None) == "PRIVATE"
                    and user_id
                ):
                    quota_service.check_personal_user_quota(
                        user_id,
                        total_file_size,
                    )
            except Exception as quota_exc:
                error_fields = ingestion_error_fields(quota_exc, "QUOTA")
                for record in lifecycle_records_by_index.values():
                    transition_file_record(
                        record["file_id"],
                        status="FAILED",
                        stage="QUOTA",
                        **error_fields,
                        error_stage="QUOTA",
                        failed_at=datetime.utcnow(),
                        updated_by=user_id,
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
            file_id = result.get("file_id") or (record or {}).get("file_id")
            if result.get("success"):
                uploaded_filenames.append(result.get("file_name"))
                uploaded_file_paths.append(result.get("object_name"))
                if file_id:
                    updated_record = transition_file_record(
                        file_id,
                        status="UPLOADED",
                        stage="UPLOAD",
                        object_name=result.get("object_name"),
                        file_size=result.get("file_size"),
                        uploaded_at=datetime.utcnow(),
                        expected_statuses=("UPLOADING",),
                        updated_by=user_id,
                    )
                    if updated_record:
                        lifecycle_records_by_index[file_index] = updated_record
                        record = updated_record
                    if record and file_id:
                        # ``uploaded_filenames`` only contains successful uploads. Keep
                        # the corresponding lifecycle records in the same success order
                        # so a partial batch cannot update the wrong file name.
                        successful_lifecycle_records.append(record)
            else:
                file_name = result.get('file_name')
                error_msg = result.get('error', 'Unknown error')
                errors.append(f"Failed to upload {file_name}: {error_msg}")
                if file_id:
                    error_fields = ingestion_error_fields(result, "UPLOAD")
                    updated_record = transition_file_record(
                        file_id,
                        status="FAILED",
                        stage="UPLOAD",
                        **error_fields,
                        error_stage="UPLOAD",
                        failed_at=datetime.utcnow(),
                        expected_statuses=("UPLOADING",),
                        updated_by=user_id,
                    )
                    if updated_record:
                        lifecycle_records_by_index[file_index] = updated_record

        # Resolve filename conflicts against existing KB documents by renaming (e.g., name -> name_1)
        if index_name:
            try:
                vdb_core = get_vector_db_core()
                existing = await ElasticSearchService.list_files(index_name, include_chunks=False, vdb_core=vdb_core)
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
                        updated_record = transition_file_record(
                            record["file_id"],
                            original_filename=effective_filename,
                            expected_statuses=("UPLOADED",),
                            updated_by=user_id,
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
            from management.services.knowledge_base.storage import (
                commit_uploaded_object,
                compensate_uploaded_objects,
            )

            try:
                for object_name in uploaded_file_paths:
                    committed = commit_uploaded_object(
                        context=storage_context,
                        object_name=object_name,
                        created_by=user_id,
                    )
                    if committed:
                        for record in lifecycle_records_by_index.values():
                            if record.get("object_name") == object_name and committed.get("storage_object_id"):
                                updated_record = transition_file_record(
                                    record["file_id"],
                                    storage_object_id=committed["storage_object_id"],
                                    expected_statuses=("UPLOADED",),
                                    updated_by=user_id,
                                )
                                if updated_record:
                                    record.update(updated_record)
                                break
                quota_service.invalidate_usage_cache(storage_context.tenant_id)
                quota_status = quota_service.check_hard_limit_post_write(
                    0,
                    index_name=storage_context.index_name,
                )
            except Exception as exc:
                error_fields = ingestion_error_fields(exc, "STORAGE_COMMIT")
                for record in lifecycle_records_by_index.values():
                    if record.get("status") in {"UPLOADING", "UPLOADED"}:
                        transition_file_record(
                            record["file_id"],
                            status="FAILED",
                            stage="STORAGE_COMMIT",
                            **error_fields,
                            error_stage="STORAGE_COMMIT",
                            failed_at=datetime.utcnow(),
                            expected_statuses=("UPLOADING", "UPLOADED"),
                            updated_by=user_id,
                        )
                compensate_uploaded_objects(
                    context=storage_context,
                    object_names=uploaded_file_paths,
                    updated_by=user_id,
                )
                quota_service.invalidate_usage_cache(storage_context.tenant_id)
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

            # Convert file content to BytesIO object
            file_obj = BytesIO(file_content)

            # Store original filename before upload
            original_filename = f.filename or ""

            # Upload file
            upload_kwargs = {
                "file_obj": file_obj,
                "file_name": original_filename,
                "prefix": actual_folder,
                "file_size": len(file_content),
            }
            if lifecycle_record and lifecycle_record.get("object_name"):
                upload_kwargs["object_name"] = lifecycle_record["object_name"]
            result = upload_fileobj(**upload_kwargs)

            # Preserve original filename in result (upload_fileobj uses it for object name generation)
            result["original_file_name"] = original_filename
            if lifecycle_record:
                result["file_id"] = lifecycle_record.get("file_id")

            # Reset file pointer for potential re-reading
            await f.seek(0)
            results.append(result)

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
    result = get_file_url(object_name=object_name, expires=expires)
    if not result["success"]:
        raise Exception(
            f"File does not exist or cannot be accessed: {result.get('error', 'Unknown error')}")
    return result


async def get_file_stream_impl(object_name: str):
    file_stream = get_file_stream(object_name=object_name)
    if file_stream is None:
        raise Exception("File not found or failed to read from storage")
    content_type = get_content_type(object_name)
    return file_stream, content_type


async def delete_file_impl(
    object_name: str,
    tenant_id: Optional[str] = None,
    updated_by: Optional[str] = None,
):
    """Delete a storage object and reconcile a tenant-owned KB ledger row."""
    reference = None
    ledger_record = None
    if tenant_id:
        from management.db.knowledge_base.storage_object import get_storage_object
        from management.services.knowledge_base.storage import resolve_storage_reference

        reference = resolve_storage_reference(object_name)
        if reference:
            is_kb_source_path = reference.object_name.startswith((
                "knowledge_base/",
                f"{ASSET_OWNER_ATTACHMENTS_PREFIX}/",
            ))
            ledger_record = get_storage_object(
                tenant_id=tenant_id,
                bucket_name=reference.bucket_name,
                object_name=reference.object_name,
            )
            if is_kb_source_path and ledger_record is None:
                raise PermissionError(
                    "The knowledge-base source object is not owned by the caller's tenant"
                )

    if reference:
        result = await run_blocking(
            "delete-storage-file",
            delete_file,
            lane="control-io",
            owner="config",
            object_name=reference.object_name,
            bucket=reference.bucket_name,
        )
    else:
        result = await run_blocking(
            "delete-storage-file",
            delete_file,
            object_name=object_name,
            lane="control-io",
            owner="config",
        )
    if not result["success"]:
        raise Exception(
            f"File does not exist or deletion failed: {result.get('error', 'Unknown error')}")

    if ledger_record and reference:
        from management.services.knowledge_base.storage import release_storage_charge

        release_storage_charge(
            tenant_id=tenant_id,
            bucket_name=reference.bucket_name,
            object_name=reference.object_name,
            updated_by=updated_by,
        )
    return result


async def list_files_impl(prefix: str, limit: Optional[int] = None):
    files = list_files(prefix=prefix)
    if limit:
        files = files[:limit]
    return files











from management.services.model.media import (
    get_llm_model,
)

from management.services.file.access import (
    check_file_access,
    check_file_access_batch,
    validate_s3_url_access,
    validate_urls_access,
)

from management.services.file.preview import (
    resolve_preview_file,
    get_preview_stream,
    _is_pdf_cache_valid,
    _convert_office_to_cached_pdf,
    _conversion_locks,
    _conversion_locks_guard,
)
