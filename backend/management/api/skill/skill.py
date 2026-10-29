# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contracts.errors.exceptions import AppException, ForbiddenError, SkillException, UnauthorizedError
from contracts.skill import SkillCreateRequest, SkillInstanceInfoRequest, SkillUpdateRequest
from contracts.constants.constants import ASSET_OWNER_SKILL_VIEW_DENIED, _NOT_FOUND_TEXT
from contracts.skill import InstallSkillsRequest
import logging
from http import HTTPStatus
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from nexent.core.concurrency import run_blocking
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse, StreamingResponse

from contracts.errors.exceptions import AppException, ForbiddenError, SkillException, UnauthorizedError
from contracts.constants.environment import ENABLE_AGENT_WORKBENCH
from contracts.agent import NL2SkillRunRequest
from contracts.skill import SkillCreateRequest, SkillInstanceInfoRequest, SkillUpdateRequest
from permissions.depends import require
from permissions.models import CurrentUser
from contracts.errors.exceptions import RunModelControlsError
from management.services.permission.asset_owner import can_view_skill
from management.services.monitor.audit import AUDIT_DETAIL_LIST_LIMIT, record_security_event
from contracts.errors.exceptions import AgentDraftEditError, ResourceBindingError
from management.services.agent.authorization import require_agent_draft_edit
from services.nl2skill_service import create_nl2skill_stream
from management.services.conversation.creation_history import (
    prepare_creation_history,
    persist_creation_stream,
)
from management.services.skill.service import SkillService, UnsupportedSkillFilePreview
from management.services.skill.transfer import get_official_skills_with_status, install_skills_from_zip_for_tenant, update_skill_list
from gateway.authentication.auth import get_current_user_id, get_current_user_info


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/skills", tags=["skills"])


def _asset_owner_skill_view_denied_response(skill: Optional[Dict[str, Any]], tenant_id: str):
    """Return a denial JSONResponse when the caller cannot view an ASSET_OWNER-scoped skill."""
    if skill and not can_view_skill(tenant_id, skill.get("tenant_id")):
        return JSONResponse(content=ASSET_OWNER_SKILL_VIEW_DENIED)
    return None


def _build_skill_update_data(request: SkillUpdateRequest) -> Dict[str, Any]:
    update_data: Dict[str, Any] = {}
    for field_name in (
        "name",
        "description",
        "content",
        "tags",
        "source",
        "group_ids",
        "ingroup_permission",
        "config_schemas",
        "config_values",
    ):
        value = getattr(request, field_name)
        if value is not None:
            update_data[field_name] = value
    if request.files is not None:
        update_data["files"] = [f.model_dump() for f in request.files]
    return update_data


@router.get("")
async def list_skills(
    tenant_id: Optional[str] = Query(None, description="Tenant ID for super admin to query specific tenant's skills"),
    authorization: Optional[str] = Header(None),
) -> JSONResponse:
    """List all available skills for the current tenant (or a specific tenant for super admin)."""
    try:
        user_id, current_tenant_id = get_current_user_id(authorization)
        # Super admin can query a specific tenant's skills; otherwise use current user's tenant
        effective_tenant_id = tenant_id if tenant_id else current_tenant_id
        service = SkillService(tenant_id=effective_tenant_id)
        skills = service.list_visible_skills(
            tenant_id=effective_tenant_id,
            user_id=user_id,
        )
        return JSONResponse(content={"skills": skills})
    except SkillException as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Error listing skills: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/official")
async def list_official_skills(
    tenant_id: Optional[str] = Query(None, description="Tenant ID for super admin to query specific tenant's skills"),
    authorization: Optional[str] = Header(None),
) -> JSONResponse:
    """List all official skills with installation status for the current tenant (or a specific tenant for super admin).

    Returns skills that have source='official', each with a status field:
      - installable: skill exists globally but not yet installed for this tenant
      - installed: skill already exists for this tenant
    """
    try:
        _, current_tenant_id = get_current_user_id(authorization)
        effective_tenant_id = tenant_id if tenant_id else current_tenant_id
        skills = get_official_skills_with_status(tenant_id=effective_tenant_id)
        return JSONResponse(content={"skills": skills})
    except Exception as e:
        logger.error(f"Error listing official skills: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/install")
async def install_skills(
    request: InstallSkillsRequest,
    http_request: Request,
    tenant_id: Optional[str] = Query(
        None, description="Tenant ID for super admin to install skills for a specific tenant"
    ),
    authorization: Optional[str] = Header(None),
) -> JSONResponse:
    """Install official skills for the current tenant (or a specific tenant for super admin).

    Uses ZIP-based installation for each skill name provided.
    Existing official skills are refreshed from the bundled ZIP. Same-name
    custom skills are preserved.
    """
    try:
        user_id, current_tenant_id = get_current_user_id(authorization)
        effective_tenant_id = tenant_id if tenant_id else current_tenant_id
        installed_names = install_skills_from_zip_for_tenant(
            skill_names=request.skill_names, tenant_id=effective_tenant_id, user_id=user_id, locale=request.locale
        )
        record_security_event(
            "skill_install",
            request=http_request,
            user_id=user_id,
            tenant_id=effective_tenant_id,
            details={"skill_names": request.skill_names[:AUDIT_DETAIL_LIST_LIMIT] if request.skill_names else None},
        )
        return JSONResponse(
            content={
                "message": "Skills installed successfully",
                "installed": installed_names,
                "total": len(installed_names),
            }
        )
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Error installing skills: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("")
async def create_skill(
    request: SkillCreateRequest, http_request: Request, authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """Create a new skill (JSON format)."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        service = SkillService(tenant_id=tenant_id)

        # Convert tool_names to tool_ids if provided
        tool_ids = request.tool_ids or []
        if request.tool_names:
            raise NotImplementedError("Tool names are not supported for skill creation")

        skill_data = {
            "name": request.name,
            "description": request.description,
            "content": request.content,
            "tool_ids": tool_ids,
            "tags": request.tags,
            "source": request.source,
            "group_ids": request.group_ids,
            "ingroup_permission": request.ingroup_permission,
            "config_schemas": request.config_schemas,
            "config_values": request.config_values,
            "files": request.files if request.files else [],
        }
        skill = service.create_skill(skill_data, tenant_id=tenant_id, user_id=user_id)
        # Skill body/description/config_values are free-form content and
        # never reach the log; name and source identify the skill.
        record_security_event(
            "skill_create",
            request=http_request,
            user_id=user_id,
            tenant_id=tenant_id,
            details={"skill_name": request.name, "source": request.source},
        )
        return JSONResponse(content=skill, status_code=201)
    except UnauthorizedError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except AppException:
        raise
    except SkillException as e:
        error_msg = str(e).lower()
        if "already exists" in error_msg:
            raise HTTPException(status_code=409, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating skill: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/upload")
async def create_skill_from_file(
    http_request: Request,
    file: UploadFile = File(..., description="SKILL.md file or ZIP archive"),
    skill_name: Optional[str] = Form(None, description="Optional skill name override"),
    source: Optional[str] = Form("custom", description="Skill source"),
    authorization: Optional[str] = Header(None),
) -> JSONResponse:
    """Create a skill from file upload.

    Supports two formats:
    - Single SKILL.md file: Extracts metadata and saves directly
    - ZIP archive: Contains SKILL.md plus scripts/assets folders
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)

        service = SkillService(tenant_id=tenant_id)
        content = await file.read()

        file_type = "auto"
        if file.filename:
            if file.filename.endswith(".zip"):
                file_type = "zip"
            elif file.filename.endswith(".md"):
                file_type = "md"

        skill = service.create_skill_from_file(
            file_content=content,
            skill_name=skill_name,
            file_type=file_type,
            source=source,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        # File content never reaches the log; filename/source identify the upload.
        record_security_event(
            "skill_upload",
            request=http_request,
            user_id=user_id,
            tenant_id=tenant_id,
            details={"filename": file.filename, "skill_name": skill_name, "source": source},
        )
        return JSONResponse(content=skill, status_code=201)
    except UnauthorizedError as e:
        logger.warning(f"Unauthorized: {e}")
        raise HTTPException(status_code=401, detail=str(e))
    except AppException:
        raise
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except SkillException as e:
        error_msg = str(e).lower()
        logger.warning(f"SkillException: {e}")
        if "already exists" in error_msg:
            raise HTTPException(status_code=409, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{skill_name}/files")
async def get_skill_file_tree(skill_name: str, authorization: Optional[str] = Header(None)) -> JSONResponse:
    """Get file tree structure of a skill."""
    try:
        _, tenant_id = get_current_user_id(authorization)
        service = SkillService(tenant_id=tenant_id)
        skill = service.get_skill(skill_name)
        if not skill:
            raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")

        denied = _asset_owner_skill_view_denied_response(skill, tenant_id)
        if denied:
            return denied

        tree = service.get_skill_file_tree(skill_name)
        if not tree:
            raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")
        return JSONResponse(content=tree)
    except HTTPException:
        raise
    except UnauthorizedError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except SkillException as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting skill file tree: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{skill_name}/files/{file_path:path}")
async def get_skill_file_content(
    skill_name: str, file_path: str, authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """Get content of a specific file within a skill.

    Args:
        skill_name: Name of the skill
        file_path: Relative path to the file within the skill directory
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        service = SkillService(tenant_id=tenant_id)
        skill = service.get_skill(skill_name)
        if not skill:
            raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")

        denied = _asset_owner_skill_view_denied_response(skill, tenant_id)
        if denied:
            return denied

        content = service.get_skill_file_content(skill_name, file_path)
        if content is None:
            raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
        return JSONResponse(
            content={
                "status": "readable",
                "content": str(content),
                "encoding": getattr(content, "encoding", "utf-8"),
            }
        )
    except HTTPException:
        raise
    except UnauthorizedError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except UnsupportedSkillFilePreview as e:
        raise HTTPException(status_code=415, detail=str(e))
    except SkillException as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting skill file content: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/{skill_name}/upload",
    responses={403: {"description": "Not authorized to update this skill"}},
)
async def update_skill_from_file(
    skill_name: str,
    http_request: Request,
    file: UploadFile = File(..., description="SKILL.md file or ZIP archive"),
    authorization: Optional[str] = Header(None),
) -> JSONResponse:
    """Update a skill from file upload.

    Supports both SKILL.md and ZIP formats.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        service = SkillService(tenant_id=tenant_id)

        content = await file.read()

        file_type = "auto"
        if file.filename:
            if file.filename.endswith(".zip"):
                file_type = "zip"
            elif file.filename.endswith(".md"):
                file_type = "md"

        skill = service.update_skill_from_file(
            skill_name=skill_name, file_content=content, file_type=file_type, user_id=user_id, tenant_id=tenant_id
        )
        # File content never reaches the log.
        record_security_event(
            "skill_update",
            request=http_request,
            user_id=user_id,
            tenant_id=tenant_id,
            details={"skill_name": skill_name, "filename": file.filename},
        )
        return JSONResponse(content=skill)
    except UnauthorizedError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except AppException:
        raise
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except SkillException as e:
        if _NOT_FOUND_TEXT in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating skill from file: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/instance")
async def get_skill_instance(
    agent_id: int = Query(..., description="Agent ID"),
    skill_id: int = Query(..., description="Skill ID"),
    version_no: int = Query(0, description="Version number (0 for draft)"),
    authorization: Optional[str] = Header(None),
) -> JSONResponse:
    """Get a specific skill instance for an agent."""
    try:
        _, tenant_id = get_current_user_id(authorization)

        service = SkillService(tenant_id=tenant_id)
        instance = service.get_skill_instance(
            agent_id=agent_id, skill_id=skill_id, tenant_id=tenant_id, version_no=version_no
        )

        if not instance:
            raise HTTPException(
                status_code=404, detail=f"Skill instance not found for agent {agent_id} and skill {skill_id}"
            )

        # Enrich with skill info from ag_skill_info_t (skill_name, skill_description, skill_content, config_schemas, config_values)
        # The instance's per-agent overrides are mapped to config_values for the frontend.
        skill = service.get_skill_by_id(skill_id, tenant_id)
        if skill:
            instance_config_values = instance.get("config_values") or {}
            instance["skill_name"] = skill.get("name")
            instance["skill_description"] = skill.get("description", "")
            instance["skill_content"] = skill.get("content", "")
            # Template defaults from YAML-enriched skill
            instance["config_schemas"] = skill.get("config_schemas") or []
            # Per-agent overrides from SkillInstance.config_values override the template defaults
            merged = dict(skill.get("config_values") or {})
            merged.update(instance_config_values)
            instance["config_values"] = merged

        return JSONResponse(content=instance)
    except UnauthorizedError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting skill instance: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/instance/update")
async def update_skill_instance(
    request: SkillInstanceInfoRequest, http_request: Request, authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """Create or update a skill instance for a specific agent.

    This allows customizing skill content for a specific agent without
    modifying the global skill definition.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        if request.version_no != 0:
            raise AgentDraftEditError("agent_not_draft")
        require_agent_draft_edit(
            agent_id=request.agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        service = SkillService(tenant_id=tenant_id)
        skill = next(
            (
                item
                for item in service.list_visible_skills(
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
                if item.get("skill_id") == request.skill_id
            ),
            None,
        )
        if not skill:
            raise ResourceBindingError("resource_not_visible")

        # Create or update skill instance
        instance = service.create_or_update_skill_instance(
            skill_info=request, tenant_id=tenant_id, user_id=user_id, version_no=request.version_no
        )

        # Enrich with template info so the frontend gets config_schemas and config_values
        instance_config_values = instance.get("config_values") or {}
        instance["skill_name"] = skill.get("name")
        instance["skill_description"] = skill.get("description", "")
        instance["skill_content"] = skill.get("content", "")
        instance["config_schemas"] = skill.get("config_schemas") or []
        merged = dict(skill.get("config_values") or {})
        merged.update(instance_config_values)
        instance["config_values"] = merged

        # config_values may embed secrets and never reaches the log.
        record_security_event(
            "skill_instance_update",
            request=http_request,
            user_id=user_id,
            tenant_id=tenant_id,
            details={"skill_id": request.skill_id, "agent_id": request.agent_id, "enabled": request.enabled},
        )
        return JSONResponse(content={"message": "Skill instance updated", "instance": instance})
    except (AgentDraftEditError, ResourceBindingError) as exc:
        status_code = (
            HTTPStatus.FORBIDDEN
            if exc.code in {"agent_read_only", "agent_deleted"}
            else HTTPStatus.NOT_FOUND
            if exc.code in {"agent_not_found", "resource_not_visible"}
            else HTTPStatus.BAD_REQUEST
        )
        raise HTTPException(
            status_code=status_code,
            detail={
                "code": exc.code,
                "message": "The requested draft resource cannot be updated.",
            },
        ) from exc
    except UnauthorizedError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except HTTPException:
        raise
    except SkillException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating skill instance: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/instance/list")
async def list_skill_instances(
    agent_id: int = Query(..., description="Agent ID to query skill instances"),
    version_no: int = Query(0, description="Version number (0 for draft)"),
    authorization: Optional[str] = Header(None),
) -> JSONResponse:
    """List all skill instances for a specific agent."""
    try:
        _, tenant_id = get_current_user_id(authorization)

        service = SkillService(tenant_id=tenant_id)

        instances = service.list_skill_instances(agent_id=agent_id, tenant_id=tenant_id, version_no=version_no)

        # Enrich with skill info from ag_skill_info_t (skill_name, skill_description, skill_content, config_values)
        # Also include config_schemas and config_values from the template (via YAML enrichment).
        # The instance's per-agent overrides (config_values) are used as-is for the frontend.
        for instance in instances:
            skill = service.get_skill_by_id(instance.get("skill_id"), tenant_id)
            if skill:
                instance["skill_name"] = skill.get("name")
                instance["skill_description"] = skill.get("description", "")
                instance["skill_content"] = skill.get("content", "")
                # Template defaults from YAML-enriched skill
                instance["config_schemas"] = skill.get("config_schemas") or []
                # Per-agent config_values from SkillInstance override template defaults
                instance["config_values"] = instance.get("config_values") or skill.get("config_values") or {}

        return JSONResponse(content={"instances": instances})
    except UnauthorizedError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.error(f"Error listing skill instances: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/scan_skill")
async def scan_and_update_skill(authorization: Optional[str] = Header(None)):
    """Scan local skill directories and update skill list in database."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        await update_skill_list(tenant_id=tenant_id, user_id=user_id)
        return JSONResponse(
            status_code=HTTPStatus.OK, content={"message": "Successfully update skill", "status": "success"}
        )
    except Exception as e:
        logger.error(f"Failed to update skill: {e}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to update skill")


@router.get("/{skill_id:int}")
async def get_skill_by_id(skill_id: int, authorization: Optional[str] = Header(None)) -> JSONResponse:
    """Get a specific skill by ID."""
    try:
        _, tenant_id = get_current_user_id(authorization)
        service = SkillService(tenant_id=tenant_id)
        skill = service.get_skill_by_id(skill_id, tenant_id=tenant_id)
        if not skill:
            raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")
        return JSONResponse(content=skill)
    except HTTPException:
        raise
    except SkillException as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("Error getting skill by ID %s", skill_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/{skill_id:int}",
    responses={
        400: {"description": "No fields to update or invalid skill data"},
        401: {"description": "Unauthorized"},
        403: {"description": "Not authorized to update this skill"},
        404: {"description": "Skill not found"},
        500: {"description": "Internal server error"},
    },
)
async def update_skill_by_id(
    skill_id: int, request: SkillUpdateRequest, http_request: Request, authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """Update an existing skill by ID."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        service = SkillService(tenant_id=tenant_id)
        update_data = _build_skill_update_data(request)

        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")

        skill = service.update_skill_by_id(
            skill_id,
            update_data,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        # patch_keys carries field names only; content/config_values values
        # are free-form and never reach the log.
        record_security_event(
            "skill_update",
            request=http_request,
            user_id=user_id,
            tenant_id=tenant_id,
            details={"skill_id": skill_id, "patch_keys": sorted(update_data.keys())[:AUDIT_DETAIL_LIST_LIMIT]},
        )
        return JSONResponse(content=skill)
    except UnauthorizedError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except SkillException as e:
        if _NOT_FOUND_TEXT in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating skill by ID %s", skill_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{skill_name}")
async def get_skill(skill_name: str, authorization: Optional[str] = Header(None)) -> JSONResponse:
    """Get a specific skill by name."""
    try:
        _, tenant_id = get_current_user_id(authorization)
        service = SkillService(tenant_id=tenant_id)
        skill = service.get_skill(skill_name, tenant_id=tenant_id)
        if not skill:
            raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")
        return JSONResponse(content=skill)
    except HTTPException:
        raise
    except SkillException as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting skill {skill_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/{skill_name}",
    responses={403: {"description": "Not authorized to update this skill"}},
)
async def update_skill(
    skill_name: str, request: SkillUpdateRequest, http_request: Request, authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """Update an existing skill.

    Audit field updated_by is set from the authenticated user only; it is not read from the JSON body.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        service = SkillService(tenant_id=tenant_id)
        update_data = {}
        if request.description is not None:
            update_data["description"] = request.description
        if request.content is not None:
            update_data["content"] = request.content
        if request.tags is not None:
            update_data["tags"] = request.tags
        if request.source is not None:
            update_data["source"] = request.source
        if request.config_schemas is not None:
            update_data["config_schemas"] = request.config_schemas
        if request.config_values is not None:
            update_data["config_values"] = request.config_values
        if request.files is not None:
            update_data["files"] = [f.model_dump() for f in request.files]

        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")

        skill = service.update_skill(
            skill_name,
            update_data,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        # patch_keys carries field names only; values never reach the log.
        record_security_event(
            "skill_update",
            request=http_request,
            user_id=user_id,
            tenant_id=tenant_id,
            details={"skill_name": skill_name, "patch_keys": sorted(update_data.keys())[:AUDIT_DETAIL_LIST_LIMIT]},
        )
        return JSONResponse(content=skill)
    except UnauthorizedError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except SkillException as e:
        if _NOT_FOUND_TEXT in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating skill {skill_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/{skill_name}")
async def delete_skill(
    skill_name: str, http_request: Request, authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """Delete a skill."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        service = SkillService(tenant_id=tenant_id)
        service.delete_skill(skill_name, tenant_id=tenant_id, user_id=user_id)
        record_security_event(
            "skill_delete",
            request=http_request,
            user_id=user_id,
            tenant_id=tenant_id,
            details={"skill_name": skill_name},
        )
        return JSONResponse(content={"message": f"Skill {skill_name} deleted successfully"})
    except UnauthorizedError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except SkillException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting skill {skill_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
