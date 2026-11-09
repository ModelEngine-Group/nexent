# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Resolve model bindings for Management and build SDK adapters."""

from typing import Any, Optional

from nexent import MessageObserver
from nexent.core.gateway import get_gateway

from contracts.constants.constants import MODEL_CONFIG_MAPPING
from infrastructure.model_adapter import _config_to_context, build_adapter_fresh as build_adapter_fresh
from infrastructure.model_adapter import get_adapter_from_config as get_adapter_from_config
from management.db.model.repository import get_model_by_model_id
from management.services.configuration.tenant.settings import tenant_config_manager


# ---- Convenience wrappers (modality-specific defaults) -------------------


def get_llm_adapter_from_config(
    cfg: Optional[dict],
    tenant_id: Optional[str] = None,
    modality: str = "llm",
    **construct_extras: Any,
):
    """LLM / long-context-LLM adapter. ``modality`` = ``"llm"`` or
    ``"llm_long_context"``."""
    return get_adapter_from_config(cfg, modality, "llm", tenant_id, **construct_extras)


def get_vlm_adapter_from_config(
    cfg: Optional[dict],
    tenant_id: Optional[str] = None,
    slot: str = "vlm",
    **construct_extras: Any,
):
    return get_adapter_from_config(cfg, "vlm", slot, tenant_id, **construct_extras)


def _fetch_slot_config(tenant_id, model_id, expected_type, slot_key):
    """Fetch a model config by model_id (with type check) or by slot key."""
    if model_id:
        cfg = get_model_by_model_id(int(model_id), tenant_id)
        if not cfg:
            raise ValueError(f"Model not found: {model_id}")
        if cfg.get("model_type") != expected_type:
            raise ValueError(
                f"Selected model {model_id} is not a {expected_type} model"
            )
        return cfg
    return tenant_config_manager.get_model_config(
        key=MODEL_CONFIG_MAPPING.get(slot_key, slot_key), tenant_id=tenant_id
    )


def get_vlm_adapter(tenant_id: str, model_id: Optional[int] = None, slot: str = "vlm"):
    """Resolve the VLM adapter directly (bridge owns config-fetch).

    Replaces ``image_service.get_vlm_model`` / ``get_video_understanding_model``.
    ``slot`` = ``"vlm"`` (image) or ``"vlm3"`` (video/audio).
    """
    cfg = _fetch_slot_config(tenant_id, model_id, expected_type=slot, slot_key=slot)
    if not cfg:
        return None
    return get_gateway().get_adapter(_config_to_context(cfg, "vlm", slot, tenant_id))


def get_llm_adapter(
    tenant_id: str, model_id: Optional[int] = None, modality: str = "llm"
):
    """Resolve the LLM (or long-context) adapter directly (bridge owns config-fetch).

    Replaces ``file_management_service.get_llm_model``. ``modality`` = ``"llm"``
    (standard) or ``"llm_long_context"`` (AnalyzeTextFile long-context).
    """
    if model_id:
        cfg = get_model_by_model_id(int(model_id), tenant_id)
        if not cfg:
            raise ValueError(f"Model not found: {model_id}")
        if cfg.get("model_type") != "llm":
            raise ValueError(f"Selected model {model_id} is not an LLM model")
    else:
        cfg = tenant_config_manager.get_model_config(
            key=MODEL_CONFIG_MAPPING["llm"], tenant_id=tenant_id
        )
    if not cfg:
        return None
    return get_gateway().get_adapter(
        _config_to_context(cfg, modality, "llm", tenant_id, observer=MessageObserver())
    )


def get_embedding_adapter_from_config(
    cfg: Optional[dict],
    tenant_id: Optional[str] = None,
    modality: str = "embedding",
    slot: str = "embedding",
    **construct_extras: Any,
):
    # modality/slot are "embedding" (text) or "multi_embedding" (multimodal);
    # normalize from cfg.model_type when caller omits it.
    mt = (cfg or {}).get("model_type")
    if mt == "multi_embedding" and modality == "embedding":
        modality = "multi_embedding"
        slot = "multiEmbedding"
    return get_adapter_from_config(cfg, modality, slot, tenant_id, **construct_extras)


def get_rerank_adapter_from_config(
    cfg: Optional[dict],
    tenant_id: Optional[str] = None,
    **construct_extras: Any,
):
    return get_adapter_from_config(
        cfg, "rerank", "rerank", tenant_id, **construct_extras
    )
