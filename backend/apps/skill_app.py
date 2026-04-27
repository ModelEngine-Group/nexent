"""Skill management HTTP endpoints."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form, Header
from starlette.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from consts.const import APP_VERSION, STREAMABLE_CONTENT_TYPES
from consts.exceptions import SkillException, UnauthorizedError
from services.skill_service import (
    SkillService,
    skill_creation_task_manager,
    stream_skill_creation,
)
from consts.model import SkillInstanceInfoRequest, SkillCreateRequest, SkillCreateInteractiveRequest, SkillUpdateRequest, SkillResponse
from utils.auth_utils import get_current_user_id, get_current_user_info
from nexent.core.agents.agent_model import ModelConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/skills", tags=["skills"])
skill_creator_router = APIRouter(prefix="/skills", tags=["nl2skill"])


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
            raise NotImplementedError("Tool names are not supported for skill creation")

        skill_data = {
            "name": request.name,
            "description": request.description,
            "content": request.content,
            "tool_ids": tool_ids,
            "tags": request.tags,
            "source": request.source,
            "params": request.params,
            "files": request.files if request.files else [],
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
    source: Optional[str] = Form("自定义", description="Skill source"),
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
            source=source,
            user_id=user_id,
            tenant_id=tenant_id
        )
        return JSONResponse(content=skill, status_code=201)
    except UnauthorizedError as e:
        logger.warning(f"Unauthorized: {e}")
        raise HTTPException(status_code=401, detail=str(e))
    except SkillException as e:
        error_msg = str(e).lower()
        logger.warning(f"SkillException: {e}")
        if "already exists" in error_msg:
            raise HTTPException(status_code=409, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {type(e).__name__}: {e}", exc_info=True)
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
        if request.tags is not None:
            update_data["tags"] = request.tags
        if request.source is not None:
            update_data["source"] = request.source
        if request.params is not None:
            update_data["params"] = request.params
        if request.files is not None:
            update_data["files"] = [f.model_dump() for f in request.files]

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


def _build_model_config_from_tenant(tenant_id: str) -> ModelConfig:
    """Build ModelConfig from tenant's quick-config LLM model."""
    from utils.config_utils import tenant_config_manager, get_model_name_from_config
    from consts.const import MODEL_CONFIG_MAPPING

    quick_config = tenant_config_manager.get_model_config(
        key=MODEL_CONFIG_MAPPING["llm"],
        tenant_id=tenant_id
    )
    if not quick_config:
        raise ValueError("No LLM model configured for tenant")

    return ModelConfig(
        cite_name=quick_config.get("display_name", "default"),
        api_key=quick_config.get("api_key", ""),
        model_name=get_model_name_from_config(quick_config),
        url=quick_config.get("base_url", ""),
        temperature=0.1,
        top_p=0.95,
        ssl_verify=True,
        model_factory=quick_config.get("model_factory")
    )


@skill_creator_router.post("/create")
async def create_skill(
    request: SkillCreateInteractiveRequest,
    authorization: Optional[str] = Header(None)
):
    """Create a skill interactively via LLM agent.

    Loads the skill creation prompt template (simple or complicated based on complexity),
    runs an internal agent with WriteSkillFileTool and ReadSkillMdTool, extracts the skill content
    from the final answer, and streams step progress and token content via SSE.

    Yields SSE events:
        - step_count: Current agent step number
        - skill_content: Token-level content (thinking, code, deep_thinking, tool output)
        - final_answer: Complete skill content with <SKILL> and <FILE> delimiters
        - done: Stream completion signal
    """
    try:
        _, tenant_id, user_language = get_current_user_info(authorization)
    except Exception as e:
        logger.error(f"Unauthorized access attempt: {e}")
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Build model config from tenant
    model_config = _build_model_config_from_tenant(tenant_id)

    # Get language from request or user preference
    lang = request.language or user_language or "zh"

    # Delegate to service layer
    task_id, generator = stream_skill_creation(
        user_request=request.user_request,
        language=lang,
        model_config=model_config,
        existing_skill=request.existing_skill,
        complexity=request.complexity or "simple"
    )

    return StreamingResponse(generator(), media_type="text/event-stream", headers={"X-Task-ID": task_id})


@skill_creator_router.get("/stop/{task_id}")
async def stop_skill_creation(
    task_id: str,
    authorization: Optional[str] = Header(None)
):
    """Stop an active skill creation task.

    Args:
        task_id: The task ID returned from the /create endpoint (passed via X-Task-ID header)
    """
    try:
        _, _ = get_current_user_id(authorization)
    except Exception as e:
        logger.error(f"Unauthorized access attempt: {e}")
        raise HTTPException(status_code=401, detail="Unauthorized")

    success = skill_creation_task_manager.stop_task(task_id)

    if success:
        return JSONResponse(content={"status": "success", "message": "Skill creation task stopped"})
    else:
        return JSONResponse(content={"status": "not_found", "message": "Task not found or already completed"}, status_code=404)
