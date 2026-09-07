"""Shared model records, capabilities and uncached modality adapters."""

import logging
from dataclasses import dataclass
from typing import Any, Optional

from consts.model import ModelConnectStatusEnum
from database.model_management_db import get_model_by_model_id, get_model_records
from services.model_gateway_service import build_adapter_fresh
from utils.config_utils import tenant_config_manager

logger = logging.getLogger(__name__)


def resolve_model_record(model_id: int, tenant_id: str | None = None, cache: dict | None = None):
    """Cache lookups only within the caller's tenant-scoped request."""
    if cache is None:
        return get_model_by_model_id(model_id, tenant_id) if tenant_id is not None else get_model_by_model_id(model_id)
    if model_id not in cache:
        cache[model_id] = get_model_by_model_id(model_id, tenant_id)
    return cache[model_id]


def is_model_available(model: dict | None) -> bool:
    """Normalize catalog connection status consistently across consumers."""
    return bool(model) and (
        ModelConnectStatusEnum.get_value(model.get("connect_status"))
        == ModelConnectStatusEnum.AVAILABLE.value
    )


@dataclass(frozen=True)
class ModelDescriptor:
    display_name: str = ""
    is_multimodal: bool = False


def get_model_descriptor(model_id: int | None, tenant_id: str) -> ModelDescriptor:
    """Resolve display name and capabilities in one best-effort catalog query."""
    if model_id is not None:
        try:
            record = resolve_model_record(model_id, tenant_id)
            if record:
                return ModelDescriptor(
                    record.get("display_name", ""), record.get("model_type") == "multi_embedding"
                )
        except Exception as exc:
            logger.warning("Failed to resolve model %s: %s", model_id, exc)
    return ModelDescriptor()


def _build_model_config(model: dict) -> dict:
    config = {
        "model_repo": model.get("model_repo", ""),
        "model_name": model["model_name"],
        "api_key": model.get("api_key", ""),
        "base_url": model.get("base_url", ""),
        "model_type": model.get("model_type", "embedding"),
        "max_tokens": model.get("max_tokens", 1024),
        "ssl_verify": model.get("ssl_verify", True),
    }
    # Carry the vendor through so multi_embedding/embedding adapters dispatch
    # to the right provider instead of silently falling back to the default.
    if model.get("model_factory"):
        config["model_factory"] = model["model_factory"]
    return config

def create_embedding_model(model: dict) -> Any:
    model_config = _build_model_config(model)
    model_type = model_config.get("model_type", "embedding")

    if model_type == "multi_embedding":
        modality, slot = "multi_embedding", "multiEmbedding"
    elif model_type == "embedding":
        modality, slot = "embedding", "embedding"
    else:
        raise ValueError(
            f"Invalid model_type '{model_type}' for model '{model_config.get('model_name')}'. "
            f"Expected 'embedding' or 'multi_embedding', got '{model_type}'. "
            f"Please check the model configuration in the model management page."
        )

    # Vendor dispatch (DashScope/Siliconflow/Jina/OpenAI) is resolved by the
    # adapter registry; per-vendor request-body formatting lives in the
    # embedding adapters. Built fresh (no gateway cache). Returns the adapter;
    # callers use adapter.get_embeddings / adapter.dimension_check unchanged.
    return build_adapter_fresh(model_config, modality, slot, None)

def get_embedding_model_by_id(tenant_id: str, model_id: int) -> tuple[Optional[Any], Optional[int]]:
    """Resolve only the explicitly configured embedding model."""
    try:
        model = resolve_model_record(model_id, tenant_id)
        if model and model.get("model_type") in ("embedding", "multi_embedding"):
            return create_embedding_model(model), model.get("model_id")
        logger.warning("Model with id %s not found or is not an embedding model", model_id)
    except Exception as exc:
        logger.warning("Failed to get embedding model by id %s: %s", model_id, exc)
    return None, None


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
    # If model_name is provided, try to find it in the tenant's models
    if model_name:
        try:
            models = get_model_records({"model_type": "rerank"}, tenant_id)
            for model in models:
                model_display_name = model.get("model_repo") + "/" + model["model_name"] if model.get("model_repo") else model["model_name"]
                if model_display_name == model_name:
                    # Found the model; vendor dispatch via the adapter registry.
                    # The adapter IS the rerank implementation (protocol sunk in
                    # 67a628cad) — return it directly, not a wrapped _inner.
                    return build_adapter_fresh(
                        model, "rerank", "rerank", tenant_id
                    )
        except Exception as e:
            logger.warning(f"Failed to get rerank model by name {model_name}: {e}")

    # Fall back to default rerank model
    model_config = tenant_config_manager.get_model_config(
        key="RERANK_ID", tenant_id=tenant_id)

    model_type = model_config.get("model_type", "")

    if model_type == "rerank":
        return build_adapter_fresh(
            model_config, "rerank", "rerank", tenant_id
        )
    else:
        return None
