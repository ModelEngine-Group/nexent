import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, Path, Query
from fastapi.responses import JSONResponse
from nexent.memory.memory_service import (
    add_memory as svc_add_memory,
    clear_memory as svc_clear_memory,
    delete_memory as svc_delete_memory,
    list_memory as svc_list_memory,
    search_memory as svc_search_memory,
)

from consts.const import (
    MEMORY_AGENT_SHARE_KEY,
    MEMORY_SWITCH_KEY,
)
from consts.model import MemoryAgentShareMode
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
from utils.memory_utils import build_memory_config

logger = logging.getLogger("memory_config_app")
logger.setLevel(logging.DEBUG)
router = APIRouter(prefix="/memory")


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def _success(message: str = "success", content: Optional[Any] = None):
    return JSONResponse(status_code=200, content={"message": message, "status": "success", "content": content})


def _error(message: str = "error"):
    return JSONResponse(status_code=400, content={"message": message, "status": "error"})


# ---------------------------------------------------------------------------
# Helper function
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Configuration Endpoints
# ---------------------------------------------------------------------------
@router.get("/config/load")
def load_configs(authorization: Optional[str] = Header(None)):
    """Load all memory-related configuration for current user."""
    try:
        user_id, _ = get_current_user_id(authorization)
        configs = get_user_configs(user_id)
        return _success(content=configs)
    except Exception as e:
        logger.error("load_configs failed: %s", e)
        return _error("Failed to load configuration")


@router.post("/config/set")
def set_single_config(
    key: str = Body(..., embed=True, description="Configuration key"),
    value: Any = Body(..., embed=True, description="Configuration value"),
    authorization: Optional[str] = Header(None),
):
    """Unified endpoint to set single-value configuration items."""
    user_id, _ = get_current_user_id(authorization)

    if key == MEMORY_SWITCH_KEY:
        enabled = bool(value) if isinstance(value, bool) else str(
            value).lower() in {"true", "1", "y", "yes", "on"}
        ok = set_memory_switch(user_id, enabled)
    elif key == MEMORY_AGENT_SHARE_KEY:
        try:
            mode = MemoryAgentShareMode(str(value))
        except ValueError:
            return _error("Invalid value for MEMORY_AGENT_SHARE (expected always/ask/never)")
        ok = set_agent_share(user_id, mode)
    else:
        return _error("Unsupported configuration key")

    return _success() if ok else _error("Failed to update configuration")


@router.post("/config/disable_agent")
def add_disable_agent(
    agent_id: str = Body(..., embed=True),
    authorization: Optional[str] = Header(None),
):
    user_id, _ = get_current_user_id(authorization)
    ok = add_disabled_agent_id(user_id, agent_id)
    return _success() if ok else _error("Failed to add disable agent id")


@router.delete("/config/disable_agent/{agent_id}")
def remove_disable_agent(
    agent_id: str = Path(...),
    authorization: Optional[str] = Header(None),
):
    user_id, _ = get_current_user_id(authorization)
    ok = remove_disabled_agent_id(user_id, agent_id)
    return _success() if ok else _error("Failed to remove disable agent id")


@router.post("/config/disable_useragent")
def add_disable_useragent(
    agent_id: str = Body(..., embed=True),
    authorization: Optional[str] = Header(None),
):
    user_id, _ = get_current_user_id(authorization)
    ok = add_disabled_useragent_id(user_id, agent_id)
    return _success() if ok else _error("Failed to add disable user-agent id")


@router.delete("/config/disable_useragent/{agent_id}")
def remove_disable_useragent(
    agent_id: str = Path(...),
    authorization: Optional[str] = Header(None),
):
    user_id, _ = get_current_user_id(authorization)
    ok = remove_disabled_useragent_id(user_id, agent_id)
    return _success() if ok else _error("Failed to remove disable user-agent id")


# ---------------------------------------------------------------------------
# Memory CRUD Endpoints
# ---------------------------------------------------------------------------
@router.post("/add")
def add_memory(
    messages: List[Dict[str, Any]
                   ] = Body(..., description="Chat messages list"),
    memory_level: str = Body(..., embed=True,
                             description="Memory level: tenant/agent/user/user_agent"),
    agent_id: Optional[str] = Body(None, embed=True),
    infer: bool = Body(
        True, embed=True, description="Whether to run LLM inference during add"),
    authorization: Optional[str] = Header(None),
):
    user_id, tenant_id = get_current_user_id(authorization)
    try:
        result = asyncio.run(svc_add_memory(
            messages=messages,
            memory_level=memory_level,
            memory_config=build_memory_config(tenant_id),
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent_id,
            infer=infer,
        ))
        return _success(content=result)
    except Exception as e:
        logger.error("add_memory error: %s", e, exc_info=True)
        return _error(str(e))


@router.post("/search")
def search_memory(
    query_text: str = Body(..., embed=True, description="Query text"),
    memory_level: str = Body(..., embed=True),
    top_k: int = Body(5, embed=True),
    agent_id: Optional[str] = Body(None, embed=True),
    authorization: Optional[str] = Header(None),
):
    user_id, tenant_id = get_current_user_id(authorization)
    try:
        results = asyncio.run(svc_search_memory(
            query_text=query_text,
            memory_level=memory_level,
            memory_config=build_memory_config(tenant_id),
            tenant_id=tenant_id,
            user_id=user_id,
            top_k=top_k,
            agent_id=agent_id,
        ))
        return _success(content=results)
    except Exception as e:
        logger.error("search_memory error: %s", e, exc_info=True)
        return _error(str(e))


@router.get("/list")
def list_memory(
    memory_level: str = Query(...,
                              description="Memory level: tenant/agent/user/user_agent"),
    agent_id: Optional[str] = Query(
        None, description="Filter by agent id if applicable"),
    authorization: Optional[str] = Header(None),
):
    user_id, tenant_id = get_current_user_id(authorization)
    try:
        payload = asyncio.run(svc_list_memory(
            memory_level=memory_level,
            memory_config=build_memory_config(tenant_id),
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent_id,
        ))
        return _success(content=payload)
    except Exception as e:
        logger.error("list_memory error: %s", e, exc_info=True)
        return _error(str(e))


@router.delete("/delete/{memory_id}")
def delete_memory(
    memory_id: str = Path(..., description="ID of memory to delete"),
    authorization: Optional[str] = Header(None),
):
    _user_id, tenant_id = get_current_user_id(authorization)
    try:
        result = asyncio.run(svc_delete_memory(
            memory_id=memory_id, memory_config=build_memory_config(tenant_id)))
        return _success(content=result)
    except Exception as e:
        logger.error("delete_memory error: %s", e, exc_info=True)
        return _error(str(e))


@router.delete("/clear")
def clear_memory(
    memory_level: str = Query(...,
                              description="Memory level: tenant/agent/user/user_agent"),
    agent_id: Optional[str] = Query(
        None, description="Filter by agent id if applicable"),
    authorization: Optional[str] = Header(None),
):
    user_id, tenant_id = get_current_user_id(authorization)
    try:
        result = asyncio.run(svc_clear_memory(
            memory_level=memory_level,
            memory_config=build_memory_config(tenant_id),
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent_id,
        ))
        return _success(content=result)
    except Exception as e:
        logger.error("clear_memory error: %s", e, exc_info=True)
        return _error(str(e))
