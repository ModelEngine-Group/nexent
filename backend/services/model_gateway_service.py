"""Backend bridge: DB model config → :class:`ModelContext` → :class:`MultimodalGateway`.

This is the *thin* Phase 2 bridge. Existing service factory functions keep
their public signatures; they fetch the model config dict (unchanged) and
delegate construction to the gateway via :func:`get_adapter_from_config`::

    cfg = tenant_config_manager.get_model_config(...)
    model = get_adapter_from_config(cfg, "llm", "llm", tenant_id,
                                    temperature=0.3, top_p=0.95)

The vendor ``if model_factory == ...`` dispatch is replaced by registry
resolution keyed on the normalized factory, so adding a vendor becomes one
``@register_adapter`` decorator + one ``_FACTORY_NORMALIZE`` entry — the
service layer is untouched.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from nexent import MessageObserver
from nexent.core.gateway import (
    LLMSampling,
    ModelContext,
    WSTransport,
    build_context,
    get_gateway,
)
from nexent.core.gateway.registry import get_registry
from consts.const import MODEL_CONFIG_MAPPING, TEST_PCM_PATH
from database.model_management_db import get_model_by_model_id, get_model_records
from utils.config_utils import get_model_name_from_config, tenant_config_manager

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
_MODALITY_DEFAULT_FACTORY: Dict[str, str] = {
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
    default = _MODALITY_DEFAULT_FACTORY.get(modality, "openai")
    if factory:
        logger.debug(
            "factory %r has no %s adapter; falling back to %r", factory, modality, default
        )
    return default


def _coalesce(*vals: Any) -> Any:
    """Return the first non-``None`` value, or ``None`` if all are ``None``.

    Unlike ``a or b``, this preserves falsy-but-valid values such as
    ``temperature=0`` or ``top_p=0`` — an explicit ``0`` must reach the
    adapter rather than being silently replaced by the cfg/default fallback.
    """
    for v in vals:
        if v is not None:
            return v
    return None


def _config_to_context(
    cfg: Optional[dict],
    modality: str,
    slot: str,
    tenant_id: Optional[str],
    **construct_extras: Any,
) -> ModelContext:
    """Build a modality-specific :class:`ModelContext` from a DB config + per-call extras.

    ``construct_extras`` carries per-call-site tuning (temperature, top_p,
    max_output_tokens, stream, observer, display_name, timeout_seconds,
    language, speed_ratio, ...) so construction is behavior-preserving. Known
    keys are mapped to typed sub-objects / subclass fields; any leftover
    (e.g. the STT-Ali ``timeout`` key) falls through to the residual ``extra``
    dict, matching the prior behavior.
    """
    cfg = cfg or {}
    factory = _normalize_factory(cfg.get("model_factory"), modality)
    needs_observer = modality in ("vlm", "llm", "llm_long_context")
    observer = construct_extras.pop("observer", None)
    if needs_observer and observer is None:
        observer = MessageObserver()

    # ---- base kwargs (通用 + cross-cutting) ----
    base: Dict[str, Any] = dict(
        model_name=construct_extras.pop("model_name", None) or get_model_name_from_config(cfg) or "",
        base_url=cfg.get("base_url", ""),
        api_key=cfg.get("api_key", ""),
        modality=modality,
        factory=factory,
        tenant_id=tenant_id,
        slot=slot,
        ssl_verify=cfg.get("ssl_verify", True),
        observer=observer,
        display_name=_coalesce(construct_extras.pop("display_name", None), cfg.get("display_name")),
        timeout_seconds=_coalesce(construct_extras.pop("timeout_seconds", None), cfg.get("timeout_seconds")),
    )

    # ---- modality-specific sub-objects / fields ----
    if modality in ("llm", "llm_long_context", "vlm"):
        # Sampling params: per-call extras override; cfg-level keys (max_tokens,
        # truncation_strategy, frequency_penalty, extra_body) for long-context/VLM.
        # _coalesce (not `or`) so temperature=0 / top_p=0 are preserved.
        base["sampling"] = LLMSampling(
            temperature=_coalesce(construct_extras.pop("temperature", None), cfg.get("temperature")),
            top_p=_coalesce(construct_extras.pop("top_p", None), cfg.get("top_p")),
            stream=construct_extras.pop("stream", None),
            max_output_tokens=_coalesce(construct_extras.pop("max_output_tokens", None), cfg.get("max_output_tokens")),
            max_tokens=cfg.get("max_tokens"),
            truncation_strategy=cfg.get("truncation_strategy"),
            frequency_penalty=cfg.get("frequency_penalty"),
            extra_body=cfg.get("extra_body"),
        )
        if modality == "vlm":
            caps = construct_extras.pop("capabilities", None)
            if caps is not None:
                base["capabilities"] = caps
    elif modality in ("stt", "tts"):
        # WS endpoint carried in base_url by the voice services; HTTP-vendor
        # (ModelEngine) STT/TTS ignore `ws` and read base_url/timeout_seconds.
        ws_url = construct_extras.pop("ws_url", None) or cfg.get("base_url")
        if ws_url:
            base["ws"] = WSTransport(
                ws_url=ws_url,
                auth_headers=construct_extras.pop("auth_headers", None),
            )
        base["model_appid"] = cfg.get("model_appid")
        base["access_token"] = cfg.get("access_token")
        if modality == "stt":
            base["language"] = construct_extras.pop("language", "zh") or "zh"
            base["audio_file_path"] = construct_extras.pop("audio_file_path", None) or TEST_PCM_PATH
        else:  # tts
            base["speed_ratio"] = float(
                _coalesce(construct_extras.pop("speed_ratio", None), cfg.get("speed_ratio"), 1.0)
            )
            base["voice"] = construct_extras.pop("voice", None) or cfg.get("voice")
            base["audio_file_path"] = construct_extras.pop("audio_file_path", None)
    elif modality in ("embedding", "multi_embedding"):
        base["embedding_dim"] = cfg.get("max_tokens", 1024)
        base["model_type"] = cfg.get("model_type")

    # ---- residual: unmapped per-call extras → extra (behavior-preserving) ----
    # e.g. the STT-Ali `timeout` key (distinct from `timeout_seconds`) falls
    # through here and is read by the Ali STT adapter's defaulted extra.get.
    if construct_extras:
        base["extra"] = {k: v for k, v in construct_extras.items() if v is not None}

    return build_context(**base)


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


def get_llm_adapter(tenant_id: str, model_id: Optional[int] = None, modality: str = "llm"):
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


def _fetch_voice_config(tenant_id, model_type):
    """Fetch an STT/TTS config from tenant_config or model_records (voice fallback)."""
    try:
        cfg = tenant_config_manager.get_model_config(tenant_id, model_type)
        if cfg and isinstance(cfg, dict):
            return cfg
    except Exception:
        pass
    try:
        records = get_model_records({"model_type": model_type}, tenant_id)
        if records:
            return records[0]
    except Exception:
        pass
    return None


def get_stt_adapter_from_params(
    model_factory: Optional[str] = None,
    model_name: Optional[str] = None,
    api_key: Optional[str] = None,
    model_appid: Optional[str] = None,
    access_token: Optional[str] = None,
    base_url: Optional[str] = None,
    language: str = "zh",
):
    """STT adapter from explicit params. Replaces ``voice_service._get_stt_model_from_config``.

    Signature mirrors the old method (minus ``self``); vendor dispatch (Ali vs Volc)
    is resolved by the registry; per-vendor Config construction lives in the STT
    adapters. Built fresh (no gateway cache) since api_key/ws_url are per-request.
    """
    cfg = {
        "model_factory": model_factory,
        "model_name": model_name,
        "api_key": api_key,
        "model_appid": model_appid,
        "access_token": access_token,
        "base_url": base_url,
    }
    return build_adapter_fresh(
        cfg, "stt", "stt", None,
        language=language,
        model_name=model_name or "qwen3-asr-flash-realtime",
        timeout=5,
    )


def get_stt_adapter_from_tenant_config(tenant_id: str, language: str = "zh"):
    """STT adapter from tenant config. Replaces ``voice_service._get_stt_model_from_tenant_config``."""
    cfg = _fetch_voice_config(tenant_id, "stt")
    if not cfg:
        return get_stt_adapter_from_params(language=language)
    return build_adapter_fresh(
        cfg, "stt", "stt", tenant_id,
        language=language,
        model_name=cfg.get("model_name") or "qwen3-asr-flash-realtime",
        timeout=5,
    )


def get_tts_adapter_from_params(
    model_factory: Optional[str] = None,
    api_key: Optional[str] = None,
    model_appid: Optional[str] = None,
    access_token: Optional[str] = None,
    speed_ratio: float = 1.0,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
):
    """TTS adapter from explicit params. Replaces ``voice_service._get_tts_model_from_config``."""
    cfg = {
        "model_factory": model_factory,
        "api_key": api_key,
        "model_appid": model_appid,
        "access_token": access_token,
        "base_url": base_url,
    }
    return build_adapter_fresh(
        cfg, "tts", "tts", None,
        model_name=model or "qwen3-tts-flash",
        speed_ratio=speed_ratio,
    )


def get_tts_adapter_from_tenant_config(tenant_id: str):
    """TTS adapter from tenant config. Replaces ``voice_service._get_tts_model_from_tenant_config``."""
    cfg = _fetch_voice_config(tenant_id, "tts")
    if not cfg:
        return get_tts_adapter_from_params()
    return build_adapter_fresh(
        cfg, "tts", "tts", tenant_id,
        model_name=cfg.get("model_name") or "qwen3-tts-flash",
        speed_ratio=float(cfg.get("speed_ratio", 1.0)),
    )


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
