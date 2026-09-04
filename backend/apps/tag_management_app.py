"""HTTP endpoints for managing fixed tenant tag libraries."""

from typing import Annotated

from consts.const import CAN_EDIT_ALL_USER_ROLES
from consts.exceptions import (
    TagManagementConflictError,
    TagManagementNotFoundError,
    ValidationError,
)
from consts.model import (
    TagAssignmentBulkOutcome,
    TagAssignmentBulkReplaceRequest,
    TagAssignmentReplaceRequest,
    TagAssignmentResponse,
    TagDefinitionCreateRequest,
    TagDefinitionResponse,
    TagDefinitionUpdateRequest,
    TagDefinitionUsageResponse,
    TagDeleteResponse,
    TagDocumentBatchStatusRequest,
    TagDocumentBatchStatusResponse,
    TagDocumentProjectionStatusResponse,
    TagHTTPConflictResponse,
    TagLegacyFlatTagsProjectionResponse,
    TagLibraryResponse,
    TagOrderUpdateRequest,
    TagResourceFilterRequest,
    TagResourceFilterResponse,
    TagStatusUpdateRequest,
    TagValueCreateRequest,
    TagValueResponse,
    TagValueUpdateRequest,
    TagValueUsageResponse,
)
from database.role_permission_db import check_role_permission
from fastapi import APIRouter, Header, HTTPException, Query
from services.tag_management_service import TagManagementService
from services.tag_resource_adapters import AuthenticatedCaller
from utils.auth_utils import get_current_user_context

router = APIRouter(prefix="/tag-libraries", tags=["tag-libraries"])
TAG_CONFLICT_RESPONSES = {409: {"model": TagHTTPConflictResponse}}


def _require_manage_context(authorization: str | None) -> tuple[str, str, str]:
    user_id, tenant_id, role = get_current_user_context(authorization)
    if not check_role_permission(role, "RESOURCE", "TAG_LIBRARY", "MANAGE"):
        raise HTTPException(
            status_code=403, detail="Tag library management permission is required"
        )
    return user_id, tenant_id, role


def _assignment_caller(authorization: str | None) -> AuthenticatedCaller:
    user_id, tenant_id, role = get_current_user_context(authorization)
    return AuthenticatedCaller(
        user_id=user_id,
        authenticated_tenant_id=tenant_id,
        role=role,
        can_edit_all=role in CAN_EDIT_ALL_USER_ROLES,
    )


@router.post(
    "/documents/batch-status",
    response_model=list[TagDocumentBatchStatusResponse],
)
async def get_document_tag_batch_status(
    request: TagDocumentBatchStatusRequest,
    authorization: str | None = Header(None),
    provider: Annotated[str | None, Query(min_length=1)] = None,
    knowledge_base_id: Annotated[str | None, Query(min_length=1)] = None,
):
    """Read-scoped batch status for documents the caller can already see."""

    caller = _assignment_caller(authorization)
    try:
        return await TagManagementService.get_document_tag_batch_status(
            caller,
            provider or "",
            knowledge_base_id or "",
            request.document_ids,
            request.predicates,
        )
    except TagManagementNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TagManagementConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "details": error.details},
        ) from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.put(
    "/assignments/{resource_type}/bulk",
    response_model=list[TagAssignmentBulkOutcome],
)
async def replace_resource_tag_assignments_bulk(
    resource_type: str,
    request: TagAssignmentBulkReplaceRequest,
    authorization: str | None = Header(None),
):
    caller = _assignment_caller(authorization)
    try:
        return await TagManagementService.replace_resource_assignments_bulk(
            caller, resource_type, request.targets
        )
    except TagManagementNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TagManagementConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "details": error.details},
        ) from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post(
    "/assignments/{resource_type}/filter",
    response_model=TagResourceFilterResponse,
)
def filter_resource_tag_assignments(
    resource_type: str,
    request: TagResourceFilterRequest,
    authorization: str | None = Header(None),
):
    """Narrow an already-authorized resource id set by tag predicates.

    Callers must supply resource ids their own list flow has already
    authorized; the tag service only narrows that set. When no predicates are
    supplied the request is echoed back unchanged. Document resources should
    continue to use the document batch-status endpoint instead.
    """
    caller = _assignment_caller(authorization)
    try:
        return TagManagementService.filter_resource_ids_for_caller(
            caller, resource_type, request.resource_ids, request.predicates
        )
    except TagManagementNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TagManagementConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "details": error.details},
        ) from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get(
    "/assignments/{resource_type}/{resource_id:path}/projection-status",
    response_model=TagDocumentProjectionStatusResponse,
)
async def get_document_tag_projection_status(
    resource_type: str,
    resource_id: str,
    authorization: str | None = Header(None),
    provider: Annotated[str | None, Query(min_length=1)] = None,
    knowledge_base_id: Annotated[str | None, Query(min_length=1)] = None,
):
    caller = _assignment_caller(authorization)
    try:
        return await TagManagementService.get_document_projection_status(
            caller,
            resource_type,
            resource_id,
            provider=provider,
            knowledge_base_id=knowledge_base_id,
        )
    except TagManagementNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TagManagementConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "details": error.details},
        ) from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get(
    "/assignments/{resource_type}/{resource_id:path}/compatibility/flat-tags",
    response_model=TagLegacyFlatTagsProjectionResponse,
)
async def get_resource_legacy_flat_tags_projection(
    resource_type: str,
    resource_id: str,
    authorization: str | None = Header(None),
    provider: Annotated[str | None, Query(min_length=1)] = None,
    knowledge_base_id: Annotated[str | None, Query(min_length=1)] = None,
):
    """Bounded deprecated flat-array projection for legacy consumers."""

    caller = _assignment_caller(authorization)
    try:
        return await TagManagementService.get_legacy_flat_tags_projection(
            caller,
            resource_type,
            resource_id,
            provider=provider,
            knowledge_base_id=knowledge_base_id,
        )
    except TagManagementNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TagManagementConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "details": error.details},
        ) from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


# Keep this catch-all route after the suffix-specific assignment routes above.
# Document identifiers may contain slashes (for example, a MinIO object path),
# which the standard single-segment converter cannot accept.
@router.get(
    "/assignments/{resource_type}/{resource_id:path}",
    response_model=TagAssignmentResponse,
)
async def get_resource_tag_assignments(
    resource_type: str,
    resource_id: str,
    authorization: str | None = Header(None),
    provider: Annotated[str | None, Query(min_length=1)] = None,
    knowledge_base_id: Annotated[str | None, Query(min_length=1)] = None,
):
    caller = _assignment_caller(authorization)
    try:
        return await TagManagementService.get_resource_assignments(
            caller,
            resource_type,
            resource_id,
            provider=provider,
            knowledge_base_id=knowledge_base_id,
        )
    except TagManagementNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TagManagementConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "details": error.details},
        ) from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.put(
    "/assignments/{resource_type}/{resource_id:path}",
    response_model=TagAssignmentResponse,
    responses=TAG_CONFLICT_RESPONSES,
)
async def replace_resource_tag_assignments(
    resource_type: str,
    resource_id: str,
    request: TagAssignmentReplaceRequest,
    authorization: str | None = Header(None),
    provider: Annotated[str | None, Query(min_length=1)] = None,
    knowledge_base_id: Annotated[str | None, Query(min_length=1)] = None,
):
    caller = _assignment_caller(authorization)
    try:
        return await TagManagementService.replace_resource_assignments(
            caller,
            resource_type,
            resource_id,
            request.value_ids,
            provider=provider,
            knowledge_base_id=knowledge_base_id,
        )
    except TagManagementNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TagManagementConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "details": error.details},
        ) from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("", response_model=list[TagLibraryResponse])
def list_tag_libraries(authorization: str | None = Header(None)):
    _, tenant_id, _ = _require_manage_context(authorization)
    try:
        return TagManagementService.list_libraries(tenant_id)
    except TagManagementNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TagManagementConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "details": error.details},
        ) from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/{bucket_id}/definitions", response_model=list[TagDefinitionResponse])
def list_tag_definitions(bucket_id: int, authorization: str | None = Header(None)):
    _, tenant_id, _ = _require_manage_context(authorization)
    try:
        return TagManagementService.list_definitions(tenant_id, bucket_id)
    except TagManagementNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TagManagementConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "details": error.details},
        ) from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post(
    "/{bucket_id}/definitions",
    response_model=TagDefinitionResponse,
    responses=TAG_CONFLICT_RESPONSES,
)
def create_tag_definition(
    bucket_id: int,
    request: TagDefinitionCreateRequest,
    authorization: str | None = Header(None),
):
    user_id, tenant_id, _ = _require_manage_context(authorization)
    try:
        return TagManagementService.create_definition(
            tenant_id, bucket_id, request, user_id
        )
    except TagManagementNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TagManagementConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "details": error.details},
        ) from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.patch(
    "/{bucket_id}/definitions/{definition_id}",
    response_model=TagDefinitionResponse,
    responses=TAG_CONFLICT_RESPONSES,
)
def update_tag_definition(
    bucket_id: int,
    definition_id: int,
    request: TagDefinitionUpdateRequest,
    authorization: str | None = Header(None),
):
    user_id, tenant_id, _ = _require_manage_context(authorization)
    try:
        return TagManagementService.update_definition(
            tenant_id, bucket_id, definition_id, request, user_id
        )
    except TagManagementNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TagManagementConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "details": error.details},
        ) from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.patch(
    "/{bucket_id}/definitions/{definition_id}/status",
    response_model=TagDefinitionResponse,
    responses=TAG_CONFLICT_RESPONSES,
)
def update_tag_definition_status(
    bucket_id: int,
    definition_id: int,
    request: TagStatusUpdateRequest,
    authorization: str | None = Header(None),
):
    user_id, tenant_id, _ = _require_manage_context(authorization)
    try:
        return TagManagementService.set_definition_status(
            tenant_id, bucket_id, definition_id, request.status, user_id
        )
    except TagManagementNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TagManagementConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "details": error.details},
        ) from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.patch(
    "/{bucket_id}/definitions/{definition_id}/order",
    response_model=TagDefinitionResponse,
    responses=TAG_CONFLICT_RESPONSES,
)
def update_tag_definition_order(
    bucket_id: int,
    definition_id: int,
    request: TagOrderUpdateRequest,
    authorization: str | None = Header(None),
):
    user_id, tenant_id, _ = _require_manage_context(authorization)
    try:
        return TagManagementService.set_definition_order(
            tenant_id, bucket_id, definition_id, request.sort_order, user_id
        )
    except TagManagementNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TagManagementConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "details": error.details},
        ) from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.patch(
    "/{bucket_id}/definitions/{definition_id}/top",
    response_model=TagDefinitionResponse,
    responses=TAG_CONFLICT_RESPONSES,
)
def move_tag_definition_to_top(
    bucket_id: int,
    definition_id: int,
    authorization: str | None = Header(None),
):
    user_id, tenant_id, _ = _require_manage_context(authorization)
    try:
        return TagManagementService.move_definition_to_top(
            tenant_id, bucket_id, definition_id, user_id
        )
    except TagManagementNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TagManagementConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "details": error.details},
        ) from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get(
    "/{bucket_id}/definitions/{definition_id}/usage",
    response_model=TagDefinitionUsageResponse,
)
def get_tag_definition_usage(
    bucket_id: int, definition_id: int, authorization: str | None = Header(None)
):
    _, tenant_id, _ = _require_manage_context(authorization)
    try:
        return TagManagementService.get_definition_usage(
            tenant_id, bucket_id, definition_id
        )
    except TagManagementNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TagManagementConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "details": error.details},
        ) from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.delete(
    "/{bucket_id}/definitions/{definition_id}",
    response_model=TagDeleteResponse,
    responses=TAG_CONFLICT_RESPONSES,
)
def delete_tag_definition(
    bucket_id: int, definition_id: int, authorization: str | None = Header(None)
):
    user_id, tenant_id, _ = _require_manage_context(authorization)
    try:
        TagManagementService.delete_definition(
            tenant_id, bucket_id, definition_id, user_id
        )
    except TagManagementNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TagManagementConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "details": error.details},
        ) from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"success": True}


@router.post(
    "/{bucket_id}/definitions/{definition_id}/values",
    response_model=TagValueResponse,
    responses=TAG_CONFLICT_RESPONSES,
)
def create_tag_value(
    bucket_id: int,
    definition_id: int,
    request: TagValueCreateRequest,
    authorization: str | None = Header(None),
):
    user_id, tenant_id, _ = _require_manage_context(authorization)
    try:
        return TagManagementService.create_value(
            tenant_id, bucket_id, definition_id, request, user_id
        )
    except TagManagementNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TagManagementConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "details": error.details},
        ) from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.patch(
    "/{bucket_id}/definitions/{definition_id}/values/{value_id}",
    response_model=TagValueResponse,
    responses=TAG_CONFLICT_RESPONSES,
)
def update_tag_value(
    bucket_id: int,
    definition_id: int,
    value_id: int,
    request: TagValueUpdateRequest,
    authorization: str | None = Header(None),
):
    user_id, tenant_id, _ = _require_manage_context(authorization)
    try:
        return TagManagementService.update_value(
            tenant_id, bucket_id, definition_id, value_id, request, user_id
        )
    except TagManagementNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TagManagementConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "details": error.details},
        ) from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.patch(
    "/{bucket_id}/definitions/{definition_id}/values/{value_id}/status",
    response_model=TagValueResponse,
    responses=TAG_CONFLICT_RESPONSES,
)
def update_tag_value_status(
    bucket_id: int,
    definition_id: int,
    value_id: int,
    request: TagStatusUpdateRequest,
    authorization: str | None = Header(None),
):
    user_id, tenant_id, _ = _require_manage_context(authorization)
    try:
        return TagManagementService.set_value_status(
            tenant_id, bucket_id, definition_id, value_id, request.status, user_id
        )
    except TagManagementNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TagManagementConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "details": error.details},
        ) from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.patch(
    "/{bucket_id}/definitions/{definition_id}/values/{value_id}/order",
    response_model=TagValueResponse,
    responses=TAG_CONFLICT_RESPONSES,
)
def update_tag_value_order(
    bucket_id: int,
    definition_id: int,
    value_id: int,
    request: TagOrderUpdateRequest,
    authorization: str | None = Header(None),
):
    user_id, tenant_id, _ = _require_manage_context(authorization)
    try:
        return TagManagementService.set_value_order(
            tenant_id, bucket_id, definition_id, value_id, request.sort_order, user_id
        )
    except TagManagementNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TagManagementConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "details": error.details},
        ) from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get(
    "/{bucket_id}/definitions/{definition_id}/values/{value_id}/usage",
    response_model=TagValueUsageResponse,
)
def get_tag_value_usage(
    bucket_id: int,
    definition_id: int,
    value_id: int,
    authorization: str | None = Header(None),
):
    _, tenant_id, _ = _require_manage_context(authorization)
    try:
        return TagManagementService.get_value_usage(
            tenant_id, bucket_id, definition_id, value_id
        )
    except TagManagementNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TagManagementConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "details": error.details},
        ) from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.delete(
    "/{bucket_id}/definitions/{definition_id}/values/{value_id}",
    response_model=TagDeleteResponse,
    responses=TAG_CONFLICT_RESPONSES,
)
def delete_tag_value(
    bucket_id: int,
    definition_id: int,
    value_id: int,
    authorization: str | None = Header(None),
):
    user_id, tenant_id, _ = _require_manage_context(authorization)
    try:
        TagManagementService.delete_value(
            tenant_id, bucket_id, definition_id, value_id, user_id
        )
    except TagManagementNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TagManagementConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error), "details": error.details},
        ) from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"success": True}
