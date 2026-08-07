"""Backend bridge: DB model config → :class:`ModelContext` → :class:`MultimodalGateway`.

This is the *thin* Phase 2 bridge. Existing service factory functions keep
their public signatures; they fetch the model config dict (unchanged) and
delegate construction to the gateway via :func:`get_adapter_from_config`::

    cfg = tenant_config_manager.get_model_config(...)
    model = get_adapter_from_config(cfg, "llm", "llm", tenant_id,
                                    temperature=0.3, top_p=0.95)._inner

The vendor ``if model_factory == ...`` dispatch is replaced by registry
resolution keyed on the normalized factory, so adding a vendor becomes one
``@register_adapter`` decorator + one ``_FACTORY_NORMALIZE`` entry — the
service layer is untouched.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from nexent import MessageObserver
from nexent.core.models.gateway import ModelContext, get_gateway
from nexent.core.models.gateway.registry import get_registry
from consts.const import TEST_PCM_PATH
from utils.config_utils import get_model_name_from_config

logger = logging.getLogger("model_gateway_service")

# Normalize vendor aliases to canonical registry factory names.
_FACTORY_NORMALIZE: Dict[str, str] = {
    "volc": "volc",
    "volcano": "volc",
    "volcengine": "volc",
    "火山引擎": "volc",
    "dashscope": "dashscope",
    "ali": "ali",
    "alibaba": "ali",
    "阿里云": "ali",
    "silicon": "siliconflow",
    "siliconflow": "siliconflow",
    "openai": "openai",
    "tokenpony": "tokenpony",
    "jina": "jina",
    "cohere": "cohere",
    "modelengine": "modelengine",
}

# Modality-specific default factory when the raw factory is empty/unknown.
_MODILITY_DEFAULT_FACTORY: Dict[str, str] = {
    "llm": "openai",
    "llm_long_context": "openai",
    "vlm": "openai",
    "embedding": "openai",
    "rerank": "openai",
    "stt": "ali",
    "tts": "ali",
    "multi_embedding": "jina",
}


def _normalize_factory(raw: Optional[str], modality: str) -> str:
    """Return the canonical registry factory for ``raw`` under ``modality``."""
    cleaned = (raw or "").strip().lower()
    factory = _FACTORY_NORMALIZE.get(cleaned, cleaned)
    # STT/TTS historically route DashScope through the Ali client.
    if modality in ("stt", "tts") and factory in ("dashscope", "ali", "alibaba"):
        factory = "ali"
    if get_registry().has(factory, modality):
        return factory
    default = _MODILITY_DEFAULT_FACTORY.get(modality, "openai")
    if factory:
        logger.debug(
            "factory %r has no %s adapter; falling back to %r", factory, modality, default
        )
    return default


def _config_to_context(
    cfg: Optional[dict],
    modality: str,
    slot: str,
    tenant_id: Optional[str],
    **construct_extras: Any,
) -> ModelContext:
    """Build a :class:`ModelContext` from a DB model-config dict + per-call extras.

    ``construct_extras`` carries per-call-site tuning (temperature, top_p,
    max_output_tokens, stream, observer, display_name, timeout_seconds, ws_url,
    max_tokens, truncation_strategy, ...) so construction is behavior-preserving.
    """
    cfg = cfg or {}
    factory = _normalize_factory(cfg.get("model_factory"), modality)
    needs_observer = modality in ("vlm", "llm", "llm_long_context")
    observer = construct_extras.pop("observer", None)
    if needs_observer and observer is None:
        observer = MessageObserver()

    extra: Dict[str, Any] = {}
    # cfg-level construction params
    for k in ("timeout_seconds", "max_tokens", "truncation_strategy", "extra_body"):
        if cfg.get(k) is not None:
            extra[k] = cfg.get(k)
    # STT/TTS WS url is carried in base_url by the services; expose as ws_url.
    if modality in ("stt", "tts") and cfg.get("base_url"):
        extra["ws_url"] = cfg.get("base_url")
    # per-call-site extras (override)
    for k, v in list(construct_extras.items()):
        if v is not None:
            extra[k] = v if k != "ws_url" else v
    # ws_url passed explicitly as kwarg
    if construct_extras.get("ws_url"):
        extra["ws_url"] = construct_extras["ws_url"]

    return ModelContext(
        model_name=construct_extras.get("model_name") or get_model_name_from_config(cfg) or "",
        base_url=cfg.get("base_url", ""),
        api_key=cfg.get("api_key", ""),
        modality=modality,
        factory=factory,
        tenant_id=tenant_id,
        slot=slot,
        ssl_verify=cfg.get("ssl_verify", True),
        embedding_dim=cfg.get("max_tokens", 1024) if modality in ("embedding", "multi_embedding") else None,
        model_type=cfg.get("model_type") if modality in ("embedding", "multi_embedding") else None,
        model_appid=cfg.get("model_appid"),
        access_token=cfg.get("access_token"),
        speed_ratio=float(construct_extras.get("speed_ratio") or cfg.get("speed_ratio", 1.0)) if modality == "tts" else 1.0,
        voice=construct_extras.get("voice") or (cfg.get("voice") if modality == "tts" else None),
        language=construct_extras.get("language", "zh") if modality == "stt" else "zh",
        audio_file_path=TEST_PCM_PATH if modality == "stt" else None,
        observer=observer,
        display_name=construct_extras.get("display_name") or cfg.get("display_name"),
        extra=extra,
    )


def get_adapter_from_config(
    cfg: Optional[dict],
    modality: str,
    slot: str,
    tenant_id: Optional[str] = None,
    **construct_extras: Any,
):
    """Resolve and return the adapter for ``cfg`` (cached by the gateway)."""
    context = _config_to_context(cfg, modality, slot, tenant_id, **construct_extras)
    return get_gateway().get_adapter(context)


def build_adapter_fresh(
    cfg: Optional[dict],
    modality: str,
    slot: str,
    tenant_id: Optional[str] = None,
    **construct_extras: Any,
):
    """Build a fresh adapter for ``cfg`` WITHOUT the gateway instance cache.

    Used by per-call construction sites (e.g. voice streaming sessions) where
    vendor config carries per-request params (api_key, ws_url, voice, …) that
    must not collide across tenants under a shared cache key.
    """
    context = _config_to_context(cfg, modality, slot, tenant_id, **construct_extras)
    cls = get_registry().resolve(context.factory, modality)
    return cls(context)


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


def get_stt_adapter_from_config(
    cfg: Optional[dict],
    tenant_id: Optional[str] = None,
    **construct_extras: Any,
):
    return get_adapter_from_config(cfg, "stt", "stt", tenant_id, **construct_extras)


def get_tts_adapter_from_config(
    cfg: Optional[dict],
    tenant_id: Optional[str] = None,
    **construct_extras: Any,
):
    return get_adapter_from_config(cfg, "tts", "tts", tenant_id, **construct_extras)


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
    return get_adapter_from_config(cfg, "rerank", "rerank", tenant_id, **construct_extras)
