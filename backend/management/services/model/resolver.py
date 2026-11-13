# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared model records, capabilities and uncached modality adapters."""

import logging
from typing import Any, Optional

from contracts.model import ModelConnectStatusEnum
from contracts.model import ModelDescriptor
from infrastructure.knowledge_search import embedding_adapter_spec
from management.db.model.repository import get_model_by_model_id, get_model_records
from management.services.model.adapter import build_adapter_fresh
from management.services.configuration.tenant.settings import tenant_config_manager

logger = logging.getLogger(__name__)


def resolve_model_record(
    model_id: int, tenant_id: str | None = None, cache: dict | None = None
):
    """Cache lookups only within the caller's tenant-scoped request."""
    if cache is None:
        return (
            get_model_by_model_id(model_id, tenant_id)
            if tenant_id is not None
            else get_model_by_model_id(model_id)
        )
    if model_id not in cache:
        cache[model_id] = get_model_by_model_id(model_id, tenant_id)
    return cache[model_id]


def is_model_available(model: dict | None) -> bool:
    """Normalize catalog connection status consistently across consumers."""
    return bool(model) and (
        ModelConnectStatusEnum.get_value(model.get("connect_status"))
        == ModelConnectStatusEnum.AVAILABLE.value
    )


def get_model_descriptor(model_id: int | None, tenant_id: str) -> ModelDescriptor:
    """Resolve display name and capabilities in one best-effort catalog query."""
    if model_id is not None:
        try:
            record = resolve_model_record(model_id, tenant_id)
            if record:
                return ModelDescriptor(
                    record.get("display_name", ""),
                    record.get("model_type") == "multi_embedding",
                )
        except Exception as exc:
            logger.warning("Failed to resolve model %s: %s", model_id, exc)
    return ModelDescriptor()


def create_embedding_model(model: dict) -> Any:
    model_config, modality, slot = embedding_adapter_spec(model)
    return build_adapter_fresh(model_config, modality, slot, None)


def get_embedding_model_by_id(
    tenant_id: str, model_id: int
) -> tuple[Optional[Any], Optional[int]]:
    """Resolve only the explicitly configured embedding model."""
    try:
        model = resolve_model_record(model_id, tenant_id)
        if model and model.get("model_type") in ("embedding", "multi_embedding"):
            return create_embedding_model(model), model.get("model_id")
        logger.warning(
            "Model with id %s not found or is not an embedding model", model_id
        )
    except Exception as exc:
        logger.warning("Failed to get embedding model by id %s: %s", model_id, exc)
    return None, None


def find_named_rerank_record(tenant_id: str, model_name: str) -> dict | None:
    for model in get_model_records({"model_type": "rerank"}, tenant_id):
        repository = model.get("model_repo")
        qualified_name = f"{repository}/{model['model_name']}" if repository else model["model_name"]
        if qualified_name == model_name:
            return model
    return None


def get_rerank_model(tenant_id: str, model_name: Optional[str] = None):
    """
    Get the rerank model for the tenant, optionally using a specific model name.

    Args:
        tenant_id: Tenant ID
        model_name: Optional specific model name to use (format: "model_repo/model_name" or just "model_name")
                   If provided, will try to find the model in the tenant's model list.

    Returns:
        Rerank model instance or None
    """
    if model_name:
        try:
            model = find_named_rerank_record(tenant_id, model_name)
            if model is not None:
                return build_adapter_fresh(model, "rerank", "rerank", tenant_id)
        except Exception as e:
            logger.warning(f"Failed to get rerank model by name {model_name}: {e}")

    # Fall back to default rerank model
    model_config = tenant_config_manager.get_model_config(
        key="RERANK_ID", tenant_id=tenant_id
    )

    model_type = model_config.get("model_type", "")

    if model_type == "rerank":
        return build_adapter_fresh(model_config, "rerank", "rerank", tenant_id)
    else:
        return None

from typing import Optional
from management.db.model.repository import get_model_by_model_id
from management.services.configuration.tenant.settings import tenant_config_manager












from typing import Optional
from management.db.model.repository import get_model_by_model_id
from management.services.configuration.tenant.settings import tenant_config_manager
