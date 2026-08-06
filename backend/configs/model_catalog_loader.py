"""Model Catalog (预置模型目录) Loader.

Responsibilities:
1. Load ``model_catalog.json`` and normalize the raw dict into memory cache.
2. Expose typed lookups: get provider info, single model profile, or a list of
   models filtered by provider + type.
3. Gracefully degrade on missing / malformed JSON so user can still configure
   models manually.  The loader never raises on import.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, Iterable, List, Optional

from consts.const import MODEL_CATALOG_JSON_PATH
from consts.model import ModelCatalogProfile, ModelCatalogProviderInfo

logger = logging.getLogger("model_catalog")

# ---------------------------------------------------------------------------
# Internal caching
# ---------------------------------------------------------------------------

#: Guard against concurrent reloads.  Hot reload is not required in v1 but we
#: still use a lock to make the first-load thread-safe under gunicorn/uvicorn.
_load_lock = threading.Lock()

#: In-memory normalized catalog.  ``None`` means "not loaded yet"; an empty
#: dict means "loaded but empty / file was missing".
_catalog_cache: Optional[Dict[str, Any]] = None


# =============================================================================
# Low-level load helpers
# =============================================================================


def _safe_load_json(path: str) -> Dict[str, Any]:
    """Load the JSON catalog file.  Never raises -- returns empty dict on failure.

    Uses ``utf-8`` (mandatory for JSON).
    """
    if not path or not os.path.isfile(path):
        logger.warning(
            "Model catalog JSON not found at path: %s. Running with empty catalog.",
            path,
        )
        return {}

    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except json.JSONDecodeError as exc:
        logger.warning(
            "Failed to parse model catalog JSON at %s: %s. Running with empty catalog.",
            path,
            exc,
        )
        return {}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to read model catalog JSON at %s: %s. Running with empty catalog.",
            path,
            exc,
        )
        return {}

    if not isinstance(data, dict):
        logger.warning(
            "Model catalog JSON top-level is not a mapping. Running with empty catalog."
        )
        return {}

    return data


def _normalize_catalog(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize the raw JSON dict into predictable internal structure.

    The returned structure::

        {
          "version": str,
          "metadata": {...},
          "providers": {
            "<provider_id>": {
              "display_name": str,
              "base_url": str,
              "models": {
                "<model_name>": ModelCatalogProfile(...)
              }
            }
          }
        }
    """
    version = str(raw.get("version") or "0.0.0")
    metadata = (
        raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    )
    raw_providers = (
        raw.get("providers") if isinstance(raw.get("providers"), dict) else {}
    )

    normalized_providers: Dict[str, Any] = {}
    for provider_id, provider_raw in raw_providers.items():
        if not isinstance(provider_raw, dict):
            continue
        provider_id_str = str(provider_id).strip()
        if not provider_id_str:
            continue

        display_name = str(provider_raw.get("display_name") or provider_id_str)
        base_url = str(provider_raw.get("base_url") or "").strip()

        raw_models = provider_raw.get("models")
        if not isinstance(raw_models, dict):
            # Provider with no models - still record it so metadata lookup works.
            normalized_providers[provider_id_str] = {
                "display_name": display_name,
                "base_url": base_url,
                "models": {},
            }
            continue

        normalized_models: Dict[str, ModelCatalogProfile] = {}
        for model_name, model_raw in raw_models.items():
            if not isinstance(model_raw, dict):
                continue
            model_name_str = str(model_name).strip()
            if not model_name_str:
                continue
            try:
                profile = _build_model_profile(
                    provider_base_url=base_url,
                    provider_factory=None,
                    model_name=model_name_str,
                    raw=model_raw,
                )
                normalized_models[model_name_str] = profile
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Skipping catalog model %s/%s: %s",
                    provider_id_str,
                    model_name_str,
                    exc,
                )

        normalized_providers[provider_id_str] = {
            "display_name": display_name,
            "base_url": base_url,
            "models": normalized_models,
        }

    return {
        "version": version,
        "metadata": metadata,
        "providers": normalized_providers,
    }


def _build_model_profile(
    *,
    provider_base_url: str,
    provider_factory: Optional[str],
    model_name: str,
    raw: Dict[str, Any],
) -> ModelCatalogProfile:
    """Merge provider-level defaults with model-level overrides into a single profile."""

    model_type = str(raw.get("model_type") or "").strip()
    if not model_type:
        raise ValueError("missing required field model_type")

    # base_url: model-level override wins, then provider-level default
    base_url_raw = (
        raw.get("base_url_override")
        or raw.get("base_url")
        or provider_base_url
    )
    base_url = str(base_url_raw).strip() if base_url_raw is not None else ""

    # model_factory: model-level override wins, then provider default, then OpenAI compatible
    factory_raw = (
        raw.get("model_factory_override")
        or raw.get("model_factory")
        or provider_factory
    )
    model_factory = (
        str(factory_raw).strip() if factory_raw else "OpenAI-API-Compatible"
    )

    display_name = str(raw.get("display_name") or "").strip() or model_name

    # Int helpers: fall back to None on non-positive / unparsable
    def _positive_int(key: str) -> Optional[int]:
        value = raw.get(key)
        if value is None:
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _bool(key: str, default: bool = False) -> bool:
        value = raw.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("1", "true", "yes", "y", "on")
        return default

    dimension = _positive_int("dimension")
    # Embedding models carry vector dimension in the legacy "max_tokens" column.
    # ``ModelCatalogProfile`` doesn't alias the column directly; the service
    # layer maps ``dimension`` -> ``max_tokens`` for embedding rows.

    return ModelCatalogProfile(
        model_type=model_type,
        display_name=display_name,
        base_url=base_url or None,
        model_factory=model_factory or None,
        context_window_tokens=_positive_int("context_window_tokens"),
        max_input_tokens=_positive_int("max_input_tokens"),
        max_output_tokens=_positive_int("max_output_tokens"),
        default_output_reserve_tokens=_positive_int("default_output_reserve_tokens"),
        tokenizer_family=(
            str(raw["tokenizer_family"]).strip()
            if raw.get("tokenizer_family")
            else None
        ),
        expected_chunk_size=_positive_int("expected_chunk_size"),
        maximum_chunk_size=_positive_int("maximum_chunk_size"),
        chunk_batch=_positive_int("chunk_batch"),
        dimension=dimension,
        timeout_seconds=_positive_int("timeout_seconds"),
        concurrency_limit=_positive_int("concurrency_limit"),
        capability_profile_version=(
            str(raw["capability_profile_version"]).strip()
            if raw.get("capability_profile_version")
            else None
        ),
        requires_appid=_bool("requires_appid"),
        requires_access_token=_bool("requires_access_token"),
    )


# =============================================================================
# Public API - caching loader
# =============================================================================


def load_model_catalog(force_reload: bool = False) -> Dict[str, Any]:
    """Load and normalize the catalog, using an in-memory cache.

    Args:
        force_reload: If true, ignore the cached value and re-read from disk.

    Returns:
        A normalized dict (see :func:`_normalize_catalog`).  On any failure
        the returned ``providers`` mapping is empty and the callers can still
        create models via manual input.
    """
    global _catalog_cache
    if _catalog_cache is not None and not force_reload:
        return _catalog_cache

    with _load_lock:
        if _catalog_cache is not None and not force_reload:
            return _catalog_cache
        raw = _safe_load_json(MODEL_CATALOG_JSON_PATH)
        normalized = _normalize_catalog(raw)
        _catalog_cache = normalized
        provider_count = len(normalized.get("providers", {}))
        model_count = sum(
            len(p.get("models", {}))
            for p in normalized.get("providers", {}).values()
        )
        logger.info(
            "Model catalog loaded: version=%s, providers=%d, models=%d",
            normalized.get("version", "?"),
            provider_count,
            model_count,
        )
        return _catalog_cache


def get_provider_info(provider_id: str) -> Optional[ModelCatalogProviderInfo]:
    """Return summary metadata for a single provider id.

    Returns ``None`` when the provider id is unknown or the catalog is empty.
    """
    if not provider_id:
        return None
    catalog = load_model_catalog()
    providers = catalog.get("providers", {})
    provider = providers.get(str(provider_id).strip())
    if not provider:
        return None

    models: Dict[str, ModelCatalogProfile] = provider.get("models") or {}
    supported_types: List[str] = []
    for profile in models.values():
        if profile.model_type not in supported_types:
            supported_types.append(profile.model_type)

    return ModelCatalogProviderInfo(
        id=str(provider_id).strip(),
        display_name=provider.get("display_name") or str(provider_id),
        base_url=provider.get("base_url") or "",
        supported_types=supported_types,
        model_count=len(models),
    )


def list_catalog_providers() -> List[ModelCatalogProviderInfo]:
    """List all providers that have at least metadata declared in the catalog."""
    catalog = load_model_catalog()
    result: List[ModelCatalogProviderInfo] = []
    for provider_id in (catalog.get("providers", {}) or {}).keys():
        info = get_provider_info(provider_id)
        if info is not None:
            result.append(info)
    return result


def get_model_profile(
    provider_id: str,
    model_name: str,
) -> Optional[ModelCatalogProfile]:
    """Look up a single model profile by (provider_id, model_name).

    The returned profile already has provider-level defaults merged in
    (``base_url``, ``model_factory``).  Returns ``None`` on miss.
    """
    if not provider_id or not model_name:
        return None
    catalog = load_model_catalog()
    provider = (catalog.get("providers", {}) or {}).get(
        str(provider_id).strip()
    )
    if not provider:
        return None
    models = provider.get("models") or {}
    return models.get(str(model_name).strip())


def list_models_by_provider(
    provider_id: str,
    model_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List catalog models for a provider, optionally filtered by model_type.

    Each returned entry is a plain dict with::

        {"model_name": str, "profile": ModelCatalogProfile.dict()}

    This format is intentionally JSON-serializable so it can be sent directly
    to the HTTP API layer.
    """
    if not provider_id:
        return []
    catalog = load_model_catalog()
    provider = (catalog.get("providers", {}) or {}).get(
        str(provider_id).strip()
    )
    if not provider:
        return []

    models = provider.get("models") or {}
    results: List[Dict[str, Any]] = []
    for model_name, profile in models.items():
        if model_type and profile.model_type != str(model_type).strip():
            continue
        results.append(
            {
                "provider_key": provider_id,
                "model_name": model_name,
                "profile": profile.model_dump(mode="json"),
            }
        )
    return results


def dump_full_catalog() -> Dict[str, Any]:
    """Return the fully-normalized catalog in one serializable payload.

    The frontend only needs a single HTTP call to fetch this payload; all
    filtering (provider, model_type) and lookups are then performed locally.

    Returned structure::

        {
          "version": "1.0.0",
          "metadata": { ... },
          "providers": [
            {
              "provider_info": ModelCatalogProviderInfo(...),
              "models": [ ModelCatalogModelEntry, ... ]
            },
            ...
          ]
        }

    Both ``provider_info`` and each entry of ``models`` use the same snake_case
    shape the existing endpoints return -- no frontend mapping is required.
    """
    catalog = load_model_catalog()
    providers_raw = catalog.get("providers", {}) or {}

    providers: List[Dict[str, Any]] = []
    for provider_id in providers_raw.keys():
        info = get_provider_info(provider_id)
        if info is None:
            continue
        models = list_models_by_provider(provider_id)
        providers.append(
            {
                "provider_info": info.model_dump(mode="json"),
                "models": models,
            }
        )

    return {
        "version": str(catalog.get("version") or "0.0.0"),
        "metadata": catalog.get("metadata") or {},
        "providers": providers,
    }


# ---------------------------------------------------------------------------
# Provider inference heuristics (used when user picks "OpenAI-API-Compatible")
# ---------------------------------------------------------------------------

#: Ordered candidates; first match wins.  The tuple is (provider_id, url_keyword).
_PROVIDER_URL_HINTS: Iterable[tuple[str, str]] = (
    ("silicon", "siliconflow"),
    ("silicon", "silicon"),
    ("dashscope", "aliyuncs"),
    ("dashscope", "dashscope"),
    ("tokenpony", "tokenpony"),
    ("volcengine", "volces"),
    ("volcengine", "volcengine"),
    ("openai", "api.openai.com"),
    ("modelengine", "modelengine"),
)


def infer_provider_from_base_url(base_url: str) -> Optional[str]:
    """Best-effort provider guess from a user-provided base URL.

    Used to enable catalog auto-fill even when the user didn't explicitly pick
    a provider (e.g. custom + OpenAI-API-Compatible path).  Returns ``None``
    when nothing matches.
    """
    if not base_url:
        return None
    lowered = str(base_url).lower()
    for provider_id, keyword in _PROVIDER_URL_HINTS:
        if keyword in lowered:
            return provider_id
    return None


# ---------------------------------------------------------------------------
# Apply catalog defaults to user model_data (used by service layer)
# ---------------------------------------------------------------------------


def apply_catalog_defaults(
    model_data: Dict[str, Any],
    provider_hint: Optional[str],
) -> bool:
    """Fill empty/absent fields in ``model_data`` from the catalog.

    Rules (priority, highest first):
      1. Any truthy user-provided value on ``model_data`` is kept untouched.
      2. A value from the matching catalog profile is used as the default.
      3. If ``provider_hint`` is empty, try to infer it from ``base_url``.

    Args:
        model_data: The mutable dict about to be persisted.  This call mutates
            it in place.
        provider_hint: Explicit provider id (silicon/dashscope/...).  Pass
            ``None`` / ``""`` to let the loader infer from URL.

    Returns:
        ``True`` when any catalog default was actually applied (useful for
        logging/metrics).  ``False`` when the profile was not found or no
        fields needed filling.
    """
    if not isinstance(model_data, dict):
        return False

    if not provider_hint:
        provider_hint = infer_provider_from_base_url(
            str(model_data.get("base_url") or "")
        )
    if not provider_hint:
        return False

    model_name = str(model_data.get("model_name") or "").strip()
    if not model_name:
        return False

    profile = get_model_profile(provider_hint, model_name)
    if profile is None:
        return False

    applied = False
    profile_dict = profile.model_dump()

    # Mapping: target field on model_data -> source field on profile.
    # Rationale: keep ModelCatalogProfile focused; map legacy aliases here so
    # the catalog schema stays stable.
    field_map: Dict[str, str] = {
        "model_type": "model_type",
        "display_name": "display_name",
        "base_url": "base_url",
        "model_factory": "model_factory",
        "context_window_tokens": "context_window_tokens",
        "max_input_tokens": "max_input_tokens",
        "max_output_tokens": "max_output_tokens",
        "default_output_reserve_tokens": "default_output_reserve_tokens",
        "tokenizer_family": "tokenizer_family",
        "expected_chunk_size": "expected_chunk_size",
        "maximum_chunk_size": "maximum_chunk_size",
        "chunk_batch": "chunk_batch",
        "timeout_seconds": "timeout_seconds",
        "concurrency_limit": "concurrency_limit",
        "capability_profile_version": "capability_profile_version",
    }

    def _is_empty(value: Any) -> bool:
        # 0 / False are allowed for int/bool flags; treat None / "" as empty.
        if value is None:
            return True
        if isinstance(value, str) and value.strip() == "":
            return True
        return False

    for target, source in field_map.items():
        if _is_empty(model_data.get(target)):
            catalog_value = profile_dict.get(source)
            if catalog_value is not None and catalog_value != "":
                model_data[target] = catalog_value
                applied = True

    # Special: embedding vector dimension -> legacy max_tokens column.
    # The existing service layer already sets max_tokens from dimension for
    # embedding records; duplicating here is safe because we only fill when
    # the target is empty.
    if profile.dimension and _is_empty(model_data.get("max_tokens")):
        current_type = model_data.get("model_type") or profile.model_type
        if current_type in ("embedding", "multi_embedding"):
            model_data["max_tokens"] = profile.dimension
            applied = True

    # STT/TTS auth-hint fields: when the profile marks them as required,
    # make sure the form fields exist so the UI can prompt the user.
    if profile.requires_appid and model_data.get("model_appid") is None:
        model_data["model_appid"] = ""
        applied = True
    if profile.requires_access_token and model_data.get("access_token") is None:
        model_data["access_token"] = ""
        applied = True

    if applied:
        # Tag capacity_source = "profile" only if the caller didn't already set one.
        if not model_data.get("capacity_source"):
            model_data["capacity_source"] = "profile"
    return applied
