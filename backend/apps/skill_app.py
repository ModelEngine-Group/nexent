"""Skill management HTTP endpoints."""

import logging
import os
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form, Header
from starlette.responses import JSONResponse
from pydantic import BaseModel

from consts.exceptions import SkillException, UnauthorizedError
from services.skill_service import SkillService
from consts.model import SkillInstanceInfoRequest
from utils.auth_utils import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/skills", tags=["skills"])


class SkillCreateRequest(BaseModel):
    """Request model for creating a skill."""
    name: str
    description: str
    content: str
    tool_ids: Optional[List[int]] = []  # Use tool_id list, link to ag_tool_info_t
    tool_names: Optional[List[str]] = []  # Alternative: use tool name list, will be converted to tool_ids
    tags: Optional[List[str]] = []
    source: Optional[str] = "custom"   # official, custom, partner
    params: Optional[Dict[str, Any]] = None  # Skill config (JSON object)


class SkillUpdateRequest(BaseModel):
    """Request model for updating a skill."""
    description: Optional[str] = None
    content: Optional[str] = None
    tool_ids: Optional[List[int]] = None  # Use tool_id list
    tool_names: Optional[List[str]] = None  # Alternative: use tool name list, will be converted to tool_ids
    tags: Optional[List[str]] = None
    source: Optional[str] = None
    params: Optional[Dict[str, Any]] = None


class SkillResponse(BaseModel):
    """Response model for skill data."""
    skill_id: int
    name: str
    description: str
    content: str
    tool_ids: List[int]
    tags: List[str]
    source: str
    params: Optional[Dict[str, Any]] = None
    created_by: Optional[str] = None
    create_time: Optional[str] = None
    updated_by: Optional[str] = None
    update_time: Optional[str] = None


# List routes first (no path parameters)
@router.get("")
async def list_skills() -> JSONResponse:
    """List all available skills."""
    try:
        service = SkillService()
        skills = service.list_skills()
        return JSONResponse(content={"skills": skills})
    except SkillException as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Error listing skills: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# POST routes
@router.post("")
async def create_skill(
    request: SkillCreateRequest,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """Create a new skill (JSON format)."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        service = SkillService()

        # Convert tool_names to tool_ids if provided
        tool_ids = request.tool_ids or []
        if request.tool_names:
            tool_ids = service.repository.get_tool_ids_by_names(request.tool_names, tenant_id)

        skill_data = {
            "name": request.name,
            "description": request.description,
            "content": request.content,
            "tool_ids": tool_ids,
            "tags": request.tags,
            "source": request.source,
            "params": request.params,
        }
        skill = service.create_skill(skill_data, user_id=user_id)
        return JSONResponse(content=skill, status_code=201)
    except UnauthorizedError as e:
        raise HTTPException(status_code=401, detail=str(e))
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
    file: UploadFile = File(..., description="SKILL.md file or ZIP archive"),
    skill_name: Optional[str] = Form(None, description="Optional skill name override"),
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """Create a skill from file upload.

    Supports two formats:
    - Single SKILL.md file: Extracts metadata and saves directly
    - ZIP archive: Contains SKILL.md plus scripts/assets folders
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        service = SkillService()

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
            user_id=user_id,
            tenant_id=tenant_id
        )
        return JSONResponse(content=skill, status_code=201)
    except UnauthorizedError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except SkillException as e:
        error_msg = str(e).lower()
        if "already exists" in error_msg:
            raise HTTPException(status_code=409, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating skill from file: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Routes with path parameters
@router.get("/{skill_name}/files")
async def get_skill_file_tree(skill_name: str) -> JSONResponse:
    """Get file tree structure of a skill."""
    try:
        service = SkillService()
        tree = service.get_skill_file_tree(skill_name)
        if not tree:
            raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")
        return JSONResponse(content=tree)
    except HTTPException:
        raise
    except SkillException as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting skill file tree: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{skill_name}/files/{file_path:path}")
async def get_skill_file_content(
    skill_name: str,
    file_path: str
) -> JSONResponse:
    """Get content of a specific file within a skill.

    Args:
        skill_name: Name of the skill
        file_path: Relative path to the file within the skill directory
    """
    try:
        service = SkillService()
        content = service.get_skill_file_content(skill_name, file_path)
        if content is None:
            raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
        return JSONResponse(content={"content": content})
    except HTTPException:
        raise
    except SkillException as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting skill file content: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/{skill_name}/upload")
async def update_skill_from_file(
    skill_name: str,
    file: UploadFile = File(..., description="SKILL.md file or ZIP archive"),
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """Update a skill from file upload.

    Supports both SKILL.md and ZIP formats.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        service = SkillService()

        content = await file.read()

        file_type = "auto"
        if file.filename:
            if file.filename.endswith(".zip"):
                file_type = "zip"
            elif file.filename.endswith(".md"):
                file_type = "md"

        skill = service.update_skill_from_file(
            skill_name=skill_name,
            file_content=content,
            file_type=file_type,
            user_id=user_id,
            tenant_id=tenant_id
        )
        return JSONResponse(content=skill)
    except UnauthorizedError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except SkillException as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating skill from file: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ============== Skill Instance APIs ==============

@router.get("/instance")
async def get_skill_instance(
    agent_id: int = Query(..., description="Agent ID"),
    skill_id: int = Query(..., description="Skill ID"),
    version_no: int = Query(0, description="Version number (0 for draft)"),
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """Get a specific skill instance for an agent."""
    try:
        _, tenant_id = get_current_user_id(authorization)

        service = SkillService()
        instance = service.get_skill_instance(
            agent_id=agent_id,
            skill_id=skill_id,
            tenant_id=tenant_id,
            version_no=version_no
        )

        if not instance:
            raise HTTPException(
                status_code=404,
                detail=f"Skill instance not found for agent {agent_id} and skill {skill_id}"
            )

        # Enrich with skill info from ag_skill_info_t (skill_name, skill_description, skill_content, params)
        skill = service.get_skill_by_id(skill_id)
        if skill:
            instance["skill_name"] = skill.get("name")
            instance["skill_description"] = skill.get("description", "")
            instance["skill_content"] = skill.get("content", "")
            instance["skill_params"] = skill.get("params") or {}

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
    request: SkillInstanceInfoRequest,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """Create or update a skill instance for a specific agent.

    This allows customizing skill content for a specific agent without
    modifying the global skill definition.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)

        # Validate skill exists
        service = SkillService()
        skill = service.get_skill_by_id(request.skill_id)
        if not skill:
            raise HTTPException(status_code=404, detail=f"Skill with ID {request.skill_id} not found")

        # Create or update skill instance
        instance = service.create_or_update_skill_instance(
            skill_info=request,
            tenant_id=tenant_id,
            user_id=user_id,
            version_no=request.version_no
        )

        return JSONResponse(content={"message": "Skill instance updated", "instance": instance})
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
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """List all skill instances for a specific agent."""
    try:
        _, tenant_id = get_current_user_id(authorization)

        service = SkillService()

        instances = service.list_skill_instances(
            agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=version_no
        )

        # Enrich with skill info from ag_skill_info_t (skill_name, skill_description, skill_content, params)
        for instance in instances:
            skill = service.get_skill_by_id(instance.get("skill_id"))
            if skill:
                instance["skill_name"] = skill.get("name")
                instance["skill_description"] = skill.get("description", "")
                instance["skill_content"] = skill.get("content", "")
                instance["skill_params"] = skill.get("params") or {}

        return JSONResponse(content={"instances": instances})
    except UnauthorizedError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.error(f"Error listing skill instances: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{skill_name}")
async def get_skill(skill_name: str) -> JSONResponse:
    """Get a specific skill by name."""
    try:
        service = SkillService()
        skill = service.get_skill(skill_name)
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


@router.put("/{skill_name}")
async def update_skill(
    skill_name: str,
    request: SkillUpdateRequest,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """Update an existing skill.

    Audit field updated_by is set from the authenticated user only; it is not read from the JSON body.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        service = SkillService()
        update_data = {}
        if request.description is not None:
            update_data["description"] = request.description
        if request.content is not None:
            update_data["content"] = request.content
        if request.tool_ids is not None:
            # Convert tool_names to tool_ids if tool_names provided, else use tool_ids directly
            if request.tool_names:
                update_data["tool_ids"] = service.repository.get_tool_ids_by_names(request.tool_names, tenant_id)
            else:
                update_data["tool_ids"] = request.tool_ids
        elif request.tool_names is not None:
            # Only tool_names provided, convert to tool_ids
            update_data["tool_ids"] = service.repository.get_tool_ids_by_names(request.tool_names, tenant_id)
        if request.tags is not None:
            update_data["tags"] = request.tags
        if request.source is not None:
            update_data["source"] = request.source
        if request.params is not None:
            update_data["params"] = request.params

        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")

        skill = service.update_skill(skill_name, update_data, user_id=user_id)
        return JSONResponse(content=skill)
    except UnauthorizedError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except SkillException as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating skill {skill_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/{skill_name}")
async def delete_skill(
    skill_name: str,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """Delete a skill."""
    try:
        user_id, _ = get_current_user_id(authorization)
        service = SkillService()
        service.delete_skill(skill_name, user_id=user_id)
        return JSONResponse(content={"message": f"Skill {skill_name} deleted successfully"})
    except UnauthorizedError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except SkillException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting skill {skill_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/{skill_name}/files/{file_path:path}")
async def delete_skill_file(
    skill_name: str,
    file_path: str,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    """Delete a specific file within a skill directory.

    Args:
        skill_name: Name of the skill
        file_path: Relative path to the file within the skill directory
    """
    try:
        _, _ = get_current_user_id(authorization)
        service = SkillService()

        # Validate skill_name so it cannot be used for path traversal
        if not skill_name:
            raise HTTPException(status_code=400, detail="Invalid skill name")
        if os.sep in skill_name or "/" in skill_name or ".." in skill_name:
            raise HTTPException(status_code=400, detail="Invalid skill name")

        # Read config to get temp_filename for validation
        config_content = service.get_skill_file_content(skill_name, "config.yaml")
        if config_content is None:
        # Normalize and validate the requested file path against temp_filename
        # Use basename to strip any directory components from file_path
        safe_file_path = os.path.basename(os.path.normpath(file_path))
        if not temp_filename or safe_file_path != temp_filename:
        import yaml
        config = yaml.safe_load(config_content)
        # Validate skill_name to avoid directory traversal or unexpected characters
        if not re.fullmatch(r"[A-Za-z0-9_-]+", skill_name):
            raise HTTPException(status_code=400, detail="Invalid skill name")

        temp_filename = config.get("temp_filename", "")

        full_path = os.path.normpath(os.path.join(local_dir, safe_file_path))
        if not temp_filename or file_path != temp_filename:
            raise HTTPException(status_code=400, detail="Can only delete temp_filename files")

        # Get the full path and validate it stays within local_dir (path traversal protection)
        local_dir = os.path.join(service.skill_manager.local_skills_dir, skill_name)
        full_path = os.path.normpath(os.path.join(local_dir, file_path))

        # Verify the normalized path is still within local_dir
            raise HTTPException(status_code=404, detail=f"File not found: {safe_file_path}")
        abs_full_path = os.path.abspath(full_path)
        if os.path.commonpath([abs_local_dir, abs_full_path]) != abs_local_dir:
            raise HTTPException(status_code=400, detail="Invalid file path: path traversal detected")

        return JSONResponse(content={"message": f"File {safe_file_path} deleted successfully"})
            raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

        os.remove(full_path)
        logger.info(f"Deleted skill file: {full_path}")

        return JSONResponse(content={"message": f"File {file_path} deleted successfully"})
    except UnauthorizedError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting skill file {skill_name}/{file_path}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
