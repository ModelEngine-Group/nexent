# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contracts.agent import AgentInfoRequest, AgentIDRequest, AgentImportRequest, SkillConflictCheckRequest, AgentNameBatchCheckRequest, AgentNameBatchRegenerateRequest, VersionPublishRequest, VersionListResponse, VersionDetailResponse, VersionStatusRequest, CurrentVersionResponse, VersionCompareRequest, VersionUpdateRequest, WorkbenchCapabilityPreviewRequest
from contracts.conversation import ConversationResponse
from contracts.tag import TagAssignmentFilter
from contracts.errors.exceptions import AgentNotFoundError, AgentRelationValidationError, ForbiddenError, SkillDuplicateError, AppException, TenantResourceLimitError, tenant_resource_limit_error_payload, ValidationError, WorkbenchError
import json
from contracts.authentication import AuthenticatedIdentity
import logging
from http import HTTPStatus
from urllib.parse import quote
from typing import Optional
from fastapi import APIRouter, Body, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from nexent.core.concurrency import run_blocking
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from starlette.responses import JSONResponse, Response, StreamingResponse

from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.constants.environment import ENABLE_AGENT_WORKBENCH
from contracts.agent import AgentInfoRequest, AgentIDRequest, AgentImportRequest, SkillConflictCheckRequest, AgentNameBatchCheckRequest, AgentNameBatchRegenerateRequest, VersionPublishRequest, VersionListResponse, VersionDetailResponse, VersionStatusRequest, CurrentVersionResponse, VersionCompareRequest, VersionUpdateRequest, WorkbenchCapabilityPreviewRequest
from contracts.conversation import ConversationResponse
from contracts.tag import TagAssignmentFilter
from contracts.errors.exceptions import AgentNotFoundError, AgentRelationValidationError, ForbiddenError, SkillDuplicateError, AppException, TenantResourceLimitError, tenant_resource_limit_error_payload, ValidationError, WorkbenchError
from permissions.depends import require
from permissions.models import CurrentUser
from management.services.permission.asset_owner import apply_agent_detail_prompt_visibility
from management.services.monitor.audit import AUDIT_DETAIL_LIST_LIMIT, record_security_event

from management.services.agent.service import (
    get_agent_info_impl,
    get_agent_icon_impl,
    update_agent_info_impl,
    upload_agent_icon_impl,
    delete_agent_impl,
    import_agent_impl,
    check_agent_name_conflict_batch_impl,
    regenerate_agent_name_batch_impl,
    list_all_agent_info_impl,
    list_agent_page_impl,
    get_agent_call_relationship_impl,
    clear_agent_new_mark_impl,
    get_agent_by_name_impl,
    export_agent_with_skills_impl,
    import_agent_with_skills_impl,
    check_skill_conflicts_impl,
)
from management.services.agent.prompt_generation import generate_guardrail_rules_impl
from management.services.knowledge_base.scope import get_agent_knowledge_capabilities
from management.services.agent.workbench import (
    build_workbench_capability_preview,
    build_workbench_main_profile,
)
from management.services.agent.system import (
    ensure_workbench_main_agent,
)
from contracts.errors.exceptions import AgentDraftEditError
from services.nl2agent_service import Nl2AgentDraftSaveError, create_nl2agent_stream
from contracts.errors.exceptions import RunModelControlsError
from management.services.conversation.creation_history import (
    prepare_creation_history,
    persist_creation_stream,
)
from management.services.agent.versions import (
    publish_version_impl,
    get_version_list_impl,
    get_version_impl,
    _get_version_detail_or_draft,
    rollback_version_impl,
    update_version_status_impl,
    update_version_impl,
    delete_version_impl,
    get_current_version_impl,
    compare_versions_impl,
    list_published_agents_impl,
)
from gateway.authentication.auth import get_current_user_info, get_current_user_id, verify_internal_runtime_jwt

agent_config_router = APIRouter(prefix="/agent")


logger = logging.getLogger("agent_app")


@agent_config_router.get("/workbench/bootstrap")
async def get_workbench_bootstrap_api(
    authorization: Optional[str] = Header(None),
):
    """Return server-authoritative Workbench modes and creation capabilities."""
    if not ENABLE_AGENT_WORKBENCH:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail={"code": "WORKBENCH_DISABLED"})
    _, tenant_id = get_current_user_id(authorization)
    try:
        generic_agent = build_workbench_main_profile(tenant_id)
    except Exception:
        # The feature may be enabled after this tenant was created. Initialize
        # lazily if the startup backfill has not reached it yet.
        try:
            await run_blocking(
                "workbench-bootstrap",
                ensure_workbench_main_agent,
                tenant_id,
                "system",
            )
            generic_agent = build_workbench_main_profile(tenant_id)
        except Exception:
            logger.exception(
                "Failed to load workbench_main presentation profile for tenant %s",
                tenant_id,
            )
            generic_agent = {
                "display_name": "Nexent Workbench",
                "default_skill_resources": [],
            }
    return {
        "code": 0,
        "message": "success",
        "data": {
            "schema_version": 3,
            "modes": {
                "generic_chat": {"enabled": True},
                "single_agent_chat": {"enabled": True},
                "multi_agent_chat": {"enabled": True},
                "skill_create": {"enabled": False},
                "agent_create": {"enabled": False},
            },
            "generic_agent": generic_agent,
        },
    }


@agent_config_router.post("/workbench/capabilities/preview")
async def preview_workbench_capabilities_api(
    request: WorkbenchCapabilityPreviewRequest,
    authorization: Optional[str] = Header(None),
):
    """Lock an Agent version and return its published Workbench defaults."""
    if not ENABLE_AGENT_WORKBENCH:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail={"code": "WORKBENCH_DISABLED"})
    user_id, tenant_id = get_current_user_id(authorization)
    try:
        data = build_workbench_capability_preview(
            agent_id=request.agent_id,
            version_no=request.version_no,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return {"code": 0, "message": "success", "data": data}
    except WorkbenchError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(exc)) from exc
    except (ValueError, ValidationError) as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail={"code": "WORKBENCH_RESOURCE_UNAVAILABLE"},
        ) from exc


@agent_config_router.get("/{agent_id}/knowledge-capabilities")
async def get_agent_knowledge_capabilities_api(
    agent_id: int,
    version_no: Optional[int] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Return knowledge source capabilities across the resolved agent tree."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        return {
            "code": 0,
            "message": "success",
            "data": await run_blocking(
                "agent-knowledge-capabilities",
                get_agent_knowledge_capabilities,
                agent_id=agent_id,
                tenant_id=tenant_id,
                version_no=version_no,
                user_id=user_id,
                lane="control-io",
                owner="management.api.agent.agent",
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to resolve agent knowledge capabilities")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to resolve agent knowledge capabilities.",
        ) from exc


@agent_config_router.post("/search_info")
async def search_agent_info_api(
    agent_id: int = Body(...),
    version_no: int = Body(0),
    tenant_id: Optional[str] = Query(None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
):
    """
    Search agent info by agent_id and version_no
    version_no defaults to 0 (current/draft version)
    Returns permission field indicating whether the user can edit this agent.
    """
    try:
        user_id, auth_tenant_id = get_current_user_id(authorization)
        # Use explicit tenant_id if provided, otherwise fall back to auth tenant_id
        effective_tenant_id = tenant_id or auth_tenant_id
        agent_info = await get_agent_info_impl(agent_id, effective_tenant_id, version_no, user_id)
        return apply_agent_detail_prompt_visibility(auth_tenant_id, agent_info)
    except AgentNotFoundError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Agent not found.") from e
    except ForbiddenError as e:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.error(f"Agent search info error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent search info error.")


@agent_config_router.get("/by-name/{agent_name}")
async def get_agent_by_name_api(
    agent_name: str,
    tenant_id: Optional[str] = Query(None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
):
    """
    Look up an agent by name and return its agent_id and highest published version_no.
    """
    try:
        _, auth_tenant_id = get_current_user_id(authorization)
        effective_tenant_id = tenant_id or auth_tenant_id
        result = get_agent_by_name_impl(agent_name, effective_tenant_id)
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except AgentNotFoundError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Agent not found.") from e
    except Exception as e:
        logger.error(f"Agent by name lookup error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent by name lookup error.")


@agent_config_router.post("/update")
async def update_agent_info_api(
    request: AgentInfoRequest, http_request: Request, authorization: Optional[str] = Header(None)
):
    """
    Update an existing agent
    """
    # Best-effort identity resolution for audit only; the service resolves
    # identity itself, so a failure here must not change endpoint behavior.
    try:
        user_id, tenant_id = get_current_user_id(authorization)
    except Exception:
        user_id, tenant_id = None, None
    # exclude_unset is what makes this the patch: fields the caller omitted
    # are not changes. Free-form content (prompts, description) never reaches
    # the log - patch_keys carries field names only.
    audit_details = {
        "agent_id": request.agent_id,
        "display_name": request.display_name,
        "model_ids": request.model_ids[:AUDIT_DETAIL_LIST_LIMIT] if request.model_ids else None,
        "patch_keys": sorted(request.model_dump(exclude_unset=True, exclude_none=True))[:AUDIT_DETAIL_LIST_LIMIT],
    }
    try:
        result = await update_agent_info_impl(request, AuthenticatedIdentity(*get_current_user_id(authorization)))
        record_security_event(
            "agent_update", request=http_request, user_id=user_id, tenant_id=tenant_id, details=audit_details
        )
        return result or {}
    except ParameterValidationError as exc:
        raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                            detail={"code": exc.category, "field": exc.path}) from None
    except AgentRelationValidationError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc)) from exc
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Agent not found.") from exc
    except ForbiddenError as exc:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail=str(exc),
        ) from exc
    except TenantResourceLimitError as exc:
        logger.warning("Agent update rejected by resource limit: %s", exc)
        return JSONResponse(
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            content=tenant_resource_limit_error_payload(exc),
        )
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Agent update error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent update error.")


@agent_config_router.post("/{agent_id}/icon")
async def upload_agent_icon_api(
    agent_id: int,
    http_request: Request,
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(None),
):
    """Upload and attach an image icon to an editable agent."""
    audit_details = {"agent_id": agent_id, "filename": file.filename}
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        content = await file.read()
        audit_details["size"] = len(content)
        result = await upload_agent_icon_impl(
            agent_id=agent_id,
            content=content,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        record_security_event(
            "agent_icon_upload", request=http_request, user_id=user_id, tenant_id=tenant_id, details=audit_details
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ForbiddenError as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Agent icon upload error")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Agent icon upload error.",
        ) from exc


@agent_config_router.get("/{agent_id}/icon")
async def get_agent_icon_api(
    agent_id: int,
    authorization: Optional[str] = Header(None),
):
    """Stream the stored icon for an agent visible to the current user."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        content, content_type = await get_agent_icon_impl(
            agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return Response(
            content=content,
            media_type=content_type,
            headers={"Cache-Control": "private, max-age=3600"},
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Agent icon retrieval error")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Agent icon retrieval error.",
        ) from exc


@agent_config_router.post("/generate_guardrail_rules")
async def generate_guardrail_rules_api(
    http_request: Request,
    description: str = Body(..., embed=True),
    model_id: int = Body(..., embed=True),
    language: str = Body("zh", embed=True),
    authorization: Optional[str] = Header(None),
):
    """Generate guardrail regex rules from a natural-language description.

    Derives tenant_id and language from the authenticated caller, delegates to
    :func:`generate_guardrail_rules_impl`, and wraps the result as JSON.

    Args:
        http_request: Incoming HTTP request, used for auth-context resolution.
        description: Natural-language description of what to match or block.
        model_id: ID of the LLM model to use for generation.
        language: Language override ('zh' or 'en'); falls back to the auth
            context language when not provided or empty.
        authorization: Bearer token header used to derive the tenant_id.

    Returns:
        JSONResponse with ``{"message": "Success", "data": <result>}`` on
        success, or ``{"message": <error>, "data": null}`` on AppException.
    """
    _, tenant_id, auth_language = get_current_user_info(authorization, http_request)
    try:
        result = generate_guardrail_rules_impl(
            description=description,
            model_id=model_id,
            tenant_id=tenant_id,
            language=auth_language or language,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "Success", "data": result},
        )
    except AppException as e:
        logger.exception(f"Generate guardrail rules error: {e}")
        return JSONResponse(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            content={"message": str(e), "data": None},
        )
    except Exception as e:
        logger.exception(f"Generate guardrail rules error: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Generate guardrail rules error.",
        )


@agent_config_router.delete("")
async def delete_agent_api(
    request: AgentIDRequest,
    tenant_id: Optional[str] = Query(None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    """
    Delete an agent
    """
    try:
        user_id, auth_tenant_id, _ = get_current_user_info(authorization, http_request)
        # Use explicit tenant_id if provided, otherwise fall back to auth tenant_id
        effective_tenant_id = tenant_id or auth_tenant_id
        await delete_agent_impl(request.agent_id, effective_tenant_id, user_id)
        record_security_event(
            "agent_delete",
            request=http_request,
            user_id=user_id,
            tenant_id=auth_tenant_id,
            details={"agent_id": request.agent_id},
        )
        return {}
    except ForbiddenError as exc:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail=str(exc),
        ) from exc
    except Exception as e:
        logger.error(f"Agent delete error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent delete error.")


@agent_config_router.post("/export")
async def export_agent_api(
    request: AgentIDRequest, http_request: Request, authorization: Optional[str] = Header(None)
):
    """
    export an agent.

    Returns a ZIP file if the agent has skill instances, otherwise returns plain JSON.
    The response Content-Type and body differ based on the agent's skill configuration.
    """
    # Best-effort identity resolution for audit only; the service resolves
    # identity itself, so a failure here must not change endpoint behavior.
    try:
        user_id, tenant_id = get_current_user_id(authorization)
    except Exception:
        user_id, tenant_id = None, None
    try:
        result = await export_agent_with_skills_impl(request.agent_id, AuthenticatedIdentity(*get_current_user_id(authorization)))
        record_security_event(
            "agent_export",
            request=http_request,
            user_id=user_id,
            tenant_id=tenant_id,
            details={"agent_id": request.agent_id},
        )
        if isinstance(result, dict) and result.get("_zip"):
            filename = result.get("filename", "agent_export.zip")
            encoded_filename = quote(filename)
            return Response(
                content=result["data"],
                media_type="application/zip",
                headers={
                    # RFC 5987 encoding supports non-ASCII agent display names
                    "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
                },
            )
        return ConversationResponse(code=0, message="success", data=result)
    except ForbiddenError as exc:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail=str(exc),
        ) from exc
    except Exception as e:
        logger.error(f"Agent export error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent export error.")


@agent_config_router.post("/import")
async def import_agent_api(
    request: AgentImportRequest, http_request: Request, authorization: Optional[str] = Header(None)
):
    """
    import an agent.

    Accepts both plain JSON (agent without skills) and JSON with embedded skill ZIPs
    (agent with skills). The skills field, if present, should contain base64-encoded
    ZIP packages for each skill.
    """
    # Best-effort identity resolution for audit only; the service resolves
    # identity itself, so a failure here must not change endpoint behavior.
    try:
        user_id, tenant_id = get_current_user_id(authorization)
    except Exception:
        user_id, tenant_id = None, None
    # Audit records identifiers and counts only; ZIP/skill payloads never reach the log.
    audit_details = {
        "source_agent_id": request.agent_info.agent_id,
        "force_import": request.force_import,
        "skills_count": len(request.skills) if request.skills else 0,
    }
    try:
        if request.skills:
            agent_id_mapping = await import_agent_with_skills_impl(
                request.agent_info,
                request.skills,
                AuthenticatedIdentity(*get_current_user_id(authorization)),
                force_import=request.force_import,
                skill_resolutions=request.skill_resolutions,
            )
        else:
            agent_id_mapping = await import_agent_impl(
                request.agent_info, AuthenticatedIdentity(*get_current_user_id(authorization)), force_import=request.force_import
            )
        record_security_event(
            "agent_import", request=http_request, user_id=user_id, tenant_id=tenant_id, details=audit_details
        )
        return {
            "agent_id": agent_id_mapping.get(request.agent_info.agent_id),
            "agent_id_mapping": agent_id_mapping,
        }
    except SkillDuplicateError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "type": "skill_duplicate",
                "duplicate_skills": exc.duplicate_names,
                "skill_conflicts": exc.skill_conflicts,
            },
        )
    except TenantResourceLimitError as exc:
        logger.warning("Agent import rejected by resource limit: %s", exc)
        return JSONResponse(
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            content=tenant_resource_limit_error_payload(exc),
        )
    except Exception as e:
        logger.error(f"Agent import error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent import error.")


@agent_config_router.post("/check_skills")
async def check_skills_api(
    request: SkillConflictCheckRequest,
    authorization: Optional[str] = Header(None),
):
    """Check bundled skill names before agent import without creating data."""
    try:
        return {
            "skill_conflicts": check_skill_conflicts_impl(
                request.skill_names,
                AuthenticatedIdentity(*get_current_user_id(authorization)),
            )
        }
    except Exception as exc:
        logger.error(f"Agent skill conflict check error: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Agent skill conflict check error.",
        ) from exc


@agent_config_router.put("/clear_new/{agent_id}")
async def clear_agent_new_mark_api(agent_id: int, authorization: Optional[str] = Header(None)):
    """
    Clear the NEW mark for an agent
    """
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization)
        affected_rows = await clear_agent_new_mark_impl(agent_id, tenant_id, user_id)
        return {"message": "Agent NEW mark cleared successfully", "affected_rows": affected_rows}
    except Exception as e:
        logger.error(f"Failed to clear agent NEW mark: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to clear agent NEW mark.")


@agent_config_router.post("/check_name")
async def check_agent_name_batch_api(request: AgentNameBatchCheckRequest, authorization: Optional[str] = Header(None)):
    """
    Batch check whether agent name/display_name conflicts exist in the tenant.
    """
    try:
        return await check_agent_name_conflict_batch_impl(request, AuthenticatedIdentity(*get_current_user_id(authorization)))
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Agent name batch check error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent name batch check error.")


@agent_config_router.post("/regenerate_name")
async def regenerate_agent_name_batch_api(
    request: AgentNameBatchRegenerateRequest, authorization: Optional[str] = Header(None)
):
    """
    Batch regenerate agent name/display_name using LLM or suffix fallback.
    """
    try:
        return await regenerate_agent_name_batch_impl(request, AuthenticatedIdentity(*get_current_user_id(authorization)))
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Agent name batch regenerate error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent name batch regenerate error.")


@agent_config_router.get("/list")
async def list_all_agent_info_api(
    tenant_id: Optional[str] = Query(None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
    request: Request = None,
):
    """
    list all agent info
    """
    try:
        user_id, auth_tenant_id, _ = get_current_user_info(authorization, request)

        if tenant_id is None:
            agent_list = await list_all_agent_info_impl(tenant_id=auth_tenant_id, user_id=user_id)
            if auth_tenant_id != ASSET_OWNER_TENANT_ID:
                asset_agent_list = await list_all_agent_info_impl(tenant_id=ASSET_OWNER_TENANT_ID, user_id=user_id)
                return agent_list + asset_agent_list
            return agent_list
        return await list_all_agent_info_impl(tenant_id=tenant_id, user_id=user_id)
    except Exception as e:
        logger.error(f"Agent list error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent list error.")


@agent_config_router.get("/list/page")
async def list_agent_page_api(
    tenant_id: Optional[str] = Query(None, description="Tenant ID for filtering"),
    permission: Optional[str] = Query(None, description="EDIT or READ_ONLY"),
    tag: Optional[str] = Query(None, description="Exact agent tag"),
    search: Optional[str] = Query(None, description="Agent name or description search"),
    created_by: Optional[str] = Query(None, description="Exact creator user ID"),
    created_by_not: Optional[str] = Query(None, description="Exclude creator user ID"),
    tag_predicates: Optional[str] = Query(None, description="Structured tag predicates as JSON"),
    search_tag_predicates: Optional[str] = Query(None, description="Text-search tag predicates as JSON"),
    page: int = Query(1, ge=1, description="Page number starting from 1"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    sort_by_update_time: bool = Query(False, description="Order by latest published version time"),
    include_repository_info: bool = Query(False, description="Include repository listings for agents on this page"),
    authorization: Optional[str] = Header(None),
    request: Request = None,
):
    """List visible agents with filters and pagination."""
    try:
        user_id, auth_tenant_id, _ = get_current_user_info(authorization, request)
        resolved_tenant_id = tenant_id or auth_tenant_id
        additional_tenant_id = (
            ASSET_OWNER_TENANT_ID if tenant_id is None and auth_tenant_id != ASSET_OWNER_TENANT_ID else None
        )
        kwargs = {
            "tenant_id": resolved_tenant_id,
            "user_id": user_id,
            "caller_tenant_id": auth_tenant_id,
            "permission": permission,
            "tag": tag,
            "search": search,
            "page": page,
            "page_size": page_size,
            "sort_by_update_time": sort_by_update_time,
            "include_repository_info": include_repository_info,
        }
        if created_by:
            kwargs["created_by"] = created_by
        if created_by_not:
            kwargs["created_by_not"] = created_by_not
        for key, raw in (("tag_predicates", tag_predicates), ("search_tag_predicates", search_tag_predicates)):
            if raw:
                parsed = json.loads(raw)
                if not isinstance(parsed, list):
                    raise ValueError(f"{key} must be a list")
                kwargs[key] = [TagAssignmentFilter.model_validate(item) for item in parsed]
        if additional_tenant_id:
            kwargs["additional_tenant_id"] = additional_tenant_id
        return await list_agent_page_impl(**kwargs)
    except ValueError as error:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(error)) from error
    except Exception as error:
        logger.error(f"Paged agent list error: {str(error)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Paged agent list error.",
        ) from error


@agent_config_router.get("/call_relationship/{agent_id}")
async def get_agent_call_relationship_api(agent_id: int, authorization: Optional[str] = Header(None)):
    """
    Get agent call relationship tree including tools and sub-agents
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        return get_agent_call_relationship_impl(agent_id, tenant_id)
    except Exception as e:
        logger.error(f"Agent call relationship error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to get agent call relationship."
        )


@agent_config_router.post("/{agent_id}/publish")
async def publish_version_api(
    agent_id: int,
    request: VersionPublishRequest,
    http_request: Request,
    authorization: str = Header(None),
):
    """
    Publish a new version
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = publish_version_impl(
            agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            version_name=request.version_name,
            release_note=request.release_note,
        )
        record_security_event(
            "agent_version_publish",
            request=http_request,
            user_id=user_id,
            tenant_id=tenant_id,
            details={"agent_id": agent_id, "version_name": request.version_name},
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Publish version error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Publish version error.")


@agent_config_router.post("/{agent_id}/versions/compare")
async def compare_versions_api(
    agent_id: int,
    request: VersionCompareRequest,
    authorization: str = Header(None),
):
    """
    Compare two versions and return their differences
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        result = compare_versions_impl(
            agent_id=agent_id,
            tenant_id=tenant_id,
            version_no_a=request.version_no_a,
            version_no_b=request.version_no_b,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=jsonable_encoder(result))
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Compare versions error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Compare versions error.")


@agent_config_router.get("/{agent_id}/versions", response_model=VersionListResponse)
async def get_version_list_api(
    agent_id: int,
    tenant_id: Optional[str] = Query(None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
    request: Request = None,
):
    """versions = session.query(AgentVersion)
    Get version list for an agent
    """
    try:
        _, auth_tenant_id, _ = get_current_user_info(authorization, request)
        # Use explicit tenant_id if provided, otherwise fall back to auth tenant_id
        effective_tenant_id = tenant_id or auth_tenant_id
        result = get_version_list_impl(
            agent_id=agent_id,
            tenant_id=effective_tenant_id,
        )
        logger.info(f"Version list: {result}")
        return JSONResponse(status_code=HTTPStatus.OK, content=jsonable_encoder(result))
    except Exception as e:
        logger.error(f"Get version list error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Get version list error.")


@agent_config_router.get("/{agent_id}/versions/{version_no}", response_model=VersionDetailResponse)
async def get_version_api(
    agent_id: int,
    version_no: int,
    authorization: str = Header(None),
):
    """
    Get version
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        result = get_version_impl(
            agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=version_no,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=jsonable_encoder(result))
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Get version detail error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Get version detail error.")


@agent_config_router.get("/{agent_id}/versions/{version_no}/detail", response_model=VersionDetailResponse)
async def get_version_detail_api(
    agent_id: int,
    version_no: int,
    authorization: str = Header(None),
):
    """
    Get version detail including snapshot data
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        result = _get_version_detail_or_draft(
            agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=version_no,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=jsonable_encoder(result))
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Get version detail error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Get version detail error.")


@agent_config_router.post("/{agent_id}/versions/{version_no}/rollback")
async def rollback_version_api(
    agent_id: int,
    version_no: int,
    http_request: Request,
    authorization: str = Header(None),
):
    """
    Rollback to a specific version by restoring draft data from that version.
    This copies the target version's snapshot (agent, tools, relations, skills)
    into the draft (version_no=0) and updates current_version_no.
    The user can then edit or re-publish from the restored state.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = rollback_version_impl(
            agent_id=agent_id,
            tenant_id=tenant_id,
            target_version_no=version_no,
        )
        record_security_event(
            "agent_version_rollback",
            request=http_request,
            user_id=user_id,
            tenant_id=tenant_id,
            details={"agent_id": agent_id, "version_no": version_no},
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Rollback version error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Rollback version error.")


@agent_config_router.patch("/{agent_id}/versions/{version_no}/status")
async def update_version_status_api(
    agent_id: int,
    version_no: int,
    request: VersionStatusRequest,
    http_request: Request,
    authorization: str = Header(None),
):
    """
    Update version status (DISABLED / ARCHIVED)
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = update_version_status_impl(
            agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            version_no=version_no,
            status=request.status,
        )
        record_security_event(
            "agent_version_status_update",
            request=http_request,
            user_id=user_id,
            tenant_id=tenant_id,
            details={"agent_id": agent_id, "version_no": version_no, "status": request.status},
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Update version status error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Update version status error.")


@agent_config_router.put("/{agent_id}/versions/{version_no}")
async def update_version_api(
    agent_id: int,
    version_no: int,
    request: VersionUpdateRequest,
    http_request: Request,
    authorization: str = Header(None),
):
    """
    Update version metadata (version_name and release_note)
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = update_version_impl(
            agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            version_no=version_no,
            version_name=request.version_name,
            release_note=request.release_note,
        )
        record_security_event(
            "agent_version_update",
            request=http_request,
            user_id=user_id,
            tenant_id=tenant_id,
            details={"agent_id": agent_id, "version_no": version_no, "version_name": request.version_name},
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Update version error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Update version error.")


@agent_config_router.delete("/{agent_id}/versions/{version_no}")
async def delete_version_api(
    agent_id: int,
    version_no: int,
    http_request: Request,
    authorization: str = Header(None),
):
    """
    Delete a version (soft delete by setting delete_flag='Y')
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = delete_version_impl(
            agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            version_no=version_no,
        )
        record_security_event(
            "agent_version_delete",
            request=http_request,
            user_id=user_id,
            tenant_id=tenant_id,
            details={"agent_id": agent_id, "version_no": version_no},
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Delete version error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Delete version error.")


@agent_config_router.get("/{agent_id}/current_version", response_model=CurrentVersionResponse)
async def get_current_version_api(
    agent_id: int,
    authorization: str = Header(None),
):
    """
    Get current published version
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        result = get_current_version_impl(
            agent_id=agent_id,
            tenant_id=tenant_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=jsonable_encoder(result))
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Get current version error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Get current version error.")


@agent_config_router.get("/published_list")
async def list_published_agents_api(
    authorization: Optional[str] = Header(None),
    request: Request = None,
):
    """
    List all published agents with their current published version information.
    """
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, request)
        agent_list = await list_published_agents_impl(tenant_id=tenant_id, user_id=user_id)
        if tenant_id != ASSET_OWNER_TENANT_ID:
            asset_agent_list = await list_published_agents_impl(tenant_id=ASSET_OWNER_TENANT_ID, user_id=user_id)
            return agent_list + asset_agent_list
        return agent_list
    except Exception as e:
        logger.error(f"Published agents list error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Published agents list error.")
