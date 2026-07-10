"""Memory configuration API endpoints for the app layer.

This module exposes HTTP endpoints under the `/memory` prefix for managing
user-level memory preferences that the new Memory system reads at agent
build time. CRUD endpoints that delegated to the legacy mem0-based
``nexent.memory.memory_service`` (``/memory/add``, ``/memory/search``,
``/memory/list``, ``/memory/delete/{memory_id}``, ``/memory/clear``) have
been removed; their callers now use the in-process ``MemoryService``
directly (or the agent-side ``StoreMemoryTool`` / ``SearchMemoryTool``).

Routes retained:
- GET  `/memory/config/load`: Load memory-related configuration for current user.
- POST `/memory/config/set`: Set a single configuration entry.
- POST `/memory/config/disable_agent`: Add a disabled agent id.
- DELETE `/memory/config/disable_agent/{agent_id}`: Remove a disabled agent id.
- POST `/memory/config/disable_useragent`: Add a disabled user-agent id.
- DELETE `/memory/config/disable_useragent/{agent_id}`: Remove a disabled user-agent id.
"""
import logging
from typing import Any, Optional

from http import HTTPStatus
from fastapi import APIRouter, Body, Header, Path, HTTPException
from fastapi.responses import JSONResponse

from consts.const import (
    MEMORY_AGENT_SHARE_KEY,
    MEMORY_SWITCH_KEY,
    BOOLEAN_TRUE_VALUES,
)
from consts.model import MemoryAgentShareMode
from consts.exceptions import UnauthorizedError
from services.memory_config_service import (
    add_disabled_agent_id,
    add_disabled_useragent_id,
    get_user_configs,
    remove_disabled_agent_id,
    remove_disabled_useragent_id,
    set_agent_share,
    set_memory_switch,
)
from utils.auth_utils import get_current_user_id

logger = logging.getLogger("memory_config_app")
logger.setLevel(logging.DEBUG)
router = APIRouter(prefix="/memory")


@router.get("/config/load")
def load_configs(authorization: Optional[str] = Header(None)):
    """Load all memory-related configuration for the current user."""
    try:
        user_id, _ = get_current_user_id(authorization)
        configs = get_user_configs(user_id)
        return JSONResponse(status_code=HTTPStatus.OK, content=configs)
    except UnauthorizedError as e:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.error("load_configs failed: %s", e)
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST,
                            detail="Failed to load configuration")


@router.post("/config/set")
def set_single_config(
    key: str = Body(..., embed=True, description="Configuration key"),
    value: Any = Body(..., embed=True, description="Configuration value"),
    authorization: Optional[str] = Header(None),
):
    """Set a single-value configuration item for the current user.

    Supported keys:
    - `MEMORY_SWITCH_KEY`: Toggle memory system on/off (boolean-like values accepted).
    - `MEMORY_AGENT_SHARE_KEY`: Set agent share mode (`always`/`ask`/`never`).
    """
    user_id, _ = get_current_user_id(authorization)

    if key == MEMORY_SWITCH_KEY:
        enabled = bool(value) if isinstance(value, bool) else str(
            value).lower() in BOOLEAN_TRUE_VALUES
        ok = set_memory_switch(user_id, enabled)
    elif key == MEMORY_AGENT_SHARE_KEY:
        try:
            mode = MemoryAgentShareMode(str(value))
        except ValueError:
            raise HTTPException(status_code=HTTPStatus.NOT_ACCEPTABLE,
                                detail="Invalid value for MEMORY_AGENT_SHARE (expected always/ask/never)")
        ok = set_agent_share(user_id, mode)
    else:
        raise HTTPException(status_code=HTTPStatus.NOT_ACCEPTABLE,
                            detail="Unsupported configuration key")

    if ok:
        return JSONResponse(status_code=HTTPStatus.OK, content={"success": True})
    raise HTTPException(status_code=HTTPStatus.BAD_REQUEST,
                        detail="Failed to update configuration")


@router.post("/config/disable_agent")
def add_disable_agent(
    agent_id: str = Body(..., embed=True),
    authorization: Optional[str] = Header(None),
):
    """Add an agent id to the user's disabled agent list."""
    user_id, _ = get_current_user_id(authorization)
    ok = add_disabled_agent_id(user_id, agent_id)
    if ok:
        return JSONResponse(status_code=HTTPStatus.OK, content={"success": True})
    raise HTTPException(status_code=HTTPStatus.BAD_REQUEST,
                        detail="Failed to add disable agent id")


@router.delete("/config/disable_agent/{agent_id}")
def remove_disable_agent(
    agent_id: str = Path(...),
    authorization: Optional[str] = Header(None),
):
    """Remove an agent id from the user's disabled agent list."""
    user_id, _ = get_current_user_id(authorization)
    ok = remove_disabled_agent_id(user_id, agent_id)
    if ok:
        return JSONResponse(status_code=HTTPStatus.OK, content={"success": True})
    raise HTTPException(status_code=HTTPStatus.BAD_REQUEST,
                        detail="Failed to remove disable agent id")


@router.post("/config/disable_useragent")
def add_disable_useragent(
    agent_id: str = Body(..., embed=True),
    authorization: Optional[str] = Header(None),
):
    """Add a user-agent id to the user's disabled user-agent list."""
    user_id, _ = get_current_user_id(authorization)
    ok = add_disabled_useragent_id(user_id, agent_id)
    if ok:
        return JSONResponse(status_code=HTTPStatus.OK, content={"success": True})
    raise HTTPException(status_code=HTTPStatus.BAD_REQUEST,
                        detail="Failed to add disable user-agent id")


@router.delete("/config/disable_useragent/{agent_id}")
def remove_disable_useragent(
    agent_id: str = Path(...),
    authorization: Optional[str] = Header(None),
):
    """Remove a user-agent id from the user's disabled user-agent list."""
    user_id, _ = get_current_user_id(authorization)
    ok = remove_disabled_useragent_id(user_id, agent_id)
    if ok:
        return JSONResponse(status_code=HTTPStatus.OK, content={"success": True})
    raise HTTPException(status_code=HTTPStatus.BAD_REQUEST,
                        detail="Failed to remove disable user-agent id")