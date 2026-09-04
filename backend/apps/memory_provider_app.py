"""HTTP endpoints for external memory provider management (Phase 3).

Provides CRUD operations for provider configurations, connectivity testing
endpoints that bypass the ``enabled`` flag, and plugin discovery.

Routes:

- POST   ``/memory/providers``                        Create provider config
- GET    ``/memory/providers``                        List all providers for tenant
- GET    ``/memory/providers/{provider_id}``          Get single provider with params
- PUT    ``/memory/providers/{provider_id}``          Update provider
- DELETE ``/memory/providers/{provider_id}``          Soft-delete provider
- POST   ``/memory/providers/{provider_id}/test-search``  Test search (bypasses enabled)
- POST   ``/memory/providers/{provider_id}/test-ingest``  Test ingest (bypasses enabled)
- GET    ``/memory/provider-plugins``                 List installed plugins

All endpoints scope results by ``tenant_id`` derived from the auth token.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Header, HTTPException, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from consts.const import MEMORY_PROVIDER_PLUGINS_DIR
from database import memory_provider_config_db, memory_provider_config_param_db
from nexent.memory.models import (
    MemoryIngestRequest,
    MemoryIngestUnit,
    MemorySearchRequest,
    ProviderErrorCode,
)
from nexent.memory.providers.retry import (
    DegradableProviderError,
    NonRetryableProviderError,
    RetryableProviderError,
)
from services.memory_external_provider_service import MemoryExternalProviderService
from services.memory_provider_config_service import MemoryProviderConfigService
from services.memory_provider_plugin_loader import PluginLoader
from utils.auth_utils import get_current_user_id


logger = logging.getLogger("memory_provider_app")
logger.setLevel(logging.INFO)
router = APIRouter(prefix="/memory", tags=["Memory Provider"])


# ---------------------------------------------------------------------------
# Singleton plugin loader and service factories
# ---------------------------------------------------------------------------

_plugin_loader: Optional[PluginLoader] = None


def _get_plugin_loader() -> PluginLoader:
    """Return the singleton PluginLoader, loading plugins on first access."""
    global _plugin_loader
    if _plugin_loader is None:
        plugins_dir = MEMORY_PROVIDER_PLUGINS_DIR or "/mnt/nexent-data/memory-provider-plugins"
        _plugin_loader = PluginLoader(plugins_dir)
        _plugin_loader.load_all()
    return _plugin_loader


def _get_config_service() -> MemoryProviderConfigService:
    return MemoryProviderConfigService(_get_plugin_loader())


def _get_provider_service() -> MemoryExternalProviderService:
    return MemoryExternalProviderService(
        _get_plugin_loader(), _get_config_service()
    )


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ProviderConfigCreate(BaseModel):
    provider_name: str
    connection_type: Literal["plugin"] = "plugin"
    enabled: bool = False
    timeout_seconds: int = 30
    params: Dict[str, str] = Field(
        ..., description="EAV params, e.g. {'plugin.name': 'mem0', 'plugin.api_key': '...'}"
    )


class ProviderConfigUpdate(BaseModel):
    provider_name: Optional[str] = None
    enabled: Optional[bool] = None
    timeout_seconds: Optional[int] = None
    params: Optional[Dict[str, str]] = None


class TestSearchRequest(BaseModel):
    query: str
    top_k: int = 5


class TestIngestRequest(BaseModel):
    units: List[Dict[str, Any]] = Field(
        ..., description="List of MemoryIngestUnit dicts"
    )


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.post("/providers")
def create_provider(
    payload: ProviderConfigCreate,
    authorization: Optional[str] = Header(None),
):
    """Create a new external memory provider configuration."""
    user_id, tenant_id = get_current_user_id(authorization)
    service = _get_config_service()
    try:
        result = service.create_provider(
            tenant_id=tenant_id,
            provider_name=payload.provider_name,
            connection_type=payload.connection_type,
            params=payload.params,
            enabled=payload.enabled,
            timeout_seconds=payload.timeout_seconds,
            created_by=user_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail=str(exc)
        )
    except Exception as exc:
        logger.error("create_provider failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to create provider configuration",
        )

    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@router.get("/providers")
def list_providers(
    authorization: Optional[str] = Header(None),
):
    """List all provider configurations for the current tenant."""
    _, tenant_id = get_current_user_id(authorization)
    service = _get_config_service()
    try:
        results = service.list_providers(tenant_id)
    except Exception as exc:
        logger.error("list_providers failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to list provider configurations",
        )

    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={"items": results, "count": len(results)},
    )


@router.get("/providers/{provider_id}")
def get_provider(
    provider_id: int = Path(..., description="Provider config primary key"),
    authorization: Optional[str] = Header(None),
):
    """Retrieve a single provider configuration with masked parameters."""
    get_current_user_id(authorization)
    service = _get_config_service()
    try:
        result = service.get_provider(provider_id)
    except Exception as exc:
        logger.error("get_provider failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve provider configuration",
        )

    if result is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Provider configuration not found",
        )

    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@router.put("/providers/{provider_id}")
def update_provider(
    payload: ProviderConfigUpdate,
    provider_id: int = Path(..., description="Provider config primary key"),
    authorization: Optional[str] = Header(None),
):
    """Update a provider configuration.

    Main-table fields are updated if present in the payload. If ``params``
    is provided, they are validated and fully replaced.
    """
    user_id, _ = get_current_user_id(authorization)
    service = _get_config_service()

    update_data: Dict[str, Any] = {}
    if payload.provider_name is not None:
        update_data["provider_name"] = payload.provider_name
    if payload.enabled is not None:
        update_data["enabled"] = payload.enabled
    if payload.timeout_seconds is not None:
        update_data["timeout_seconds"] = payload.timeout_seconds
    if payload.params is not None:
        update_data["params"] = payload.params

    try:
        result = service.update_provider(provider_id, update_data, updated_by=user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail=str(exc)
        )
    except Exception as exc:
        logger.error("update_provider failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update provider configuration",
        )

    if result is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Provider configuration not found",
        )

    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@router.delete("/providers/{provider_id}")
def delete_provider(
    provider_id: int = Path(..., description="Provider config primary key"),
    authorization: Optional[str] = Header(None),
):
    """Soft-delete a provider configuration and its parameters."""
    user_id, _ = get_current_user_id(authorization)
    service = _get_config_service()
    try:
        ok = service.delete_provider(provider_id, updated_by=user_id)
    except Exception as exc:
        logger.error("delete_provider failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to delete provider configuration",
        )

    if not ok:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Failed to delete provider configuration",
        )

    return JSONResponse(status_code=HTTPStatus.OK, content={"success": True})


# ---------------------------------------------------------------------------
# Test endpoints (bypass enabled check, update last_error_code)
# ---------------------------------------------------------------------------


def _extract_error_code(exc: Exception) -> str:
    """Extract a ProviderErrorCode string from a provider exception."""
    if isinstance(exc, (NonRetryableProviderError, RetryableProviderError, DegradableProviderError)):
        if exc.error and exc.error.code:
            return exc.error.code.value
    return ProviderErrorCode.UNKNOWN.value


def _update_last_error_code(provider_id: int, error_code: Optional[str]) -> None:
    """Persist the test result error code (None on success)."""
    memory_provider_config_db.update_provider_config(
        provider_id, {"last_error_code": error_code}
    )


@router.post("/providers/{provider_id}/test-search")
async def test_search(
    payload: TestSearchRequest,
    provider_id: int = Path(..., description="Provider config primary key"),
    authorization: Optional[str] = Header(None),
):
    """Test search against a provider, bypassing the ``enabled`` flag.

    Updates ``last_error_code``: cleared on success, set to error code on failure.
    """
    user_id, tenant_id = get_current_user_id(authorization)

    config = memory_provider_config_db.get_provider_config(provider_id)
    if config is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Provider configuration not found",
        )

    params = memory_provider_config_param_db.get_params(provider_id)
    provider_service = _get_provider_service()

    search_request = MemorySearchRequest(
        query=payload.query,
        tenant_id=tenant_id,
        user_id=user_id,
        top_k=payload.top_k,
        limit=payload.top_k,
    )

    try:
        provider = provider_service.build_provider(config, params)
        results = await provider.search(search_request, limit=payload.top_k)
        _update_last_error_code(provider_id, None)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "items": [r.model_dump() for r in results],
                "count": len(results),
            },
        )
    except (NonRetryableProviderError, RetryableProviderError, DegradableProviderError) as exc:
        error_code = _extract_error_code(exc)
        _update_last_error_code(provider_id, error_code)
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f"Provider test-search failed: {exc}",
        )
    except ValueError as exc:
        _update_last_error_code(provider_id, ProviderErrorCode.INVALID_PAYLOAD.value)
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail=str(exc)
        )
    except Exception as exc:
        logger.error("test_search unexpected error: %s", exc, exc_info=True)
        _update_last_error_code(provider_id, ProviderErrorCode.UNKNOWN.value)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Provider test-search failed with unexpected error",
        )


@router.post("/providers/{provider_id}/test-ingest")
async def test_ingest(
    payload: TestIngestRequest,
    provider_id: int = Path(..., description="Provider config primary key"),
    authorization: Optional[str] = Header(None),
):
    """Test ingest against a provider, bypassing the ``enabled`` flag.

    Updates ``last_error_code``: cleared on success, set to error code on failure.
    """
    user_id, tenant_id = get_current_user_id(authorization)

    config = memory_provider_config_db.get_provider_config(provider_id)
    if config is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Provider configuration not found",
        )

    params = memory_provider_config_param_db.get_params(provider_id)
    provider_service = _get_provider_service()

    try:
        units = [MemoryIngestUnit(**u) for u in payload.units]
    except Exception as exc:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f"Invalid ingest unit format: {exc}",
        )

    ingest_request = MemoryIngestRequest(
        tenant_id=tenant_id,
        user_id=user_id,
        units=units,
        idempotency_key=f"test-ingest:{provider_id}:{user_id}",
    )

    try:
        provider = provider_service.build_provider(config, params)
        result = await provider.ingest(ingest_request)
        _update_last_error_code(provider_id, None)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content=result.model_dump(),
        )
    except (NonRetryableProviderError, RetryableProviderError, DegradableProviderError) as exc:
        error_code = _extract_error_code(exc)
        _update_last_error_code(provider_id, error_code)
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f"Provider test-ingest failed: {exc}",
        )
    except ValueError as exc:
        _update_last_error_code(provider_id, ProviderErrorCode.INVALID_PAYLOAD.value)
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail=str(exc)
        )
    except Exception as exc:
        logger.error("test_ingest unexpected error: %s", exc, exc_info=True)
        _update_last_error_code(provider_id, ProviderErrorCode.UNKNOWN.value)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Provider test-ingest failed with unexpected error",
        )


# ---------------------------------------------------------------------------
# Plugin discovery
# ---------------------------------------------------------------------------


@router.get("/provider-plugins")
def list_plugins(
    authorization: Optional[str] = Header(None),
):
    """List all installed memory provider plugins with their metadata."""
    get_current_user_id(authorization)
    plugin_loader = _get_plugin_loader()
    plugins = plugin_loader.list_plugins()

    items = [
        {
            "name": p.name,
            "version": p.version,
            "description": p.description,
            "implements": p.implements,
            "config_schema": p.config_schema,
        }
        for p in plugins
    ]

    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={"items": items, "count": len(items)},
    )
