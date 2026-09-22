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
import re
import threading
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlsplit, urlunsplit

from consts.const import MODEL_CATALOG_JSON_PATH, MODELS_DEV_CATALOG_JSON_PATH
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

# Raw models.dev data is kept separate from the operator-maintained Nexent
# catalog.  A missing downloaded file intentionally falls back to the legacy
# resolver; an existing file is authoritative and prevents stale heuristics.
_models_dev_cache: Optional[Dict[str, Any]] = None


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


def _load_models_dev_catalog(force_reload: bool = False) -> Optional[Dict[str, Any]]:
    """Load the build-time models.dev snapshot, returning None when unavailable."""
    global _models_dev_cache
    if _models_dev_cache is not None and not force_reload:
        return _models_dev_cache
    if not MODELS_DEV_CATALOG_JSON_PATH or not os.path.isfile(MODELS_DEV_CATALOG_JSON_PATH):
        return None
    try:
        with open(MODELS_DEV_CATALOG_JSON_PATH, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load models.dev catalog: %s", exc)
        return None
    if not isinstance(data, dict) or not isinstance(data.get("providers"), dict):
        logger.warning("Ignoring malformed models.dev catalog: providers must be a mapping")
        return None
    _models_dev_cache = data
    return data


def _normalize_provider_models(
    provider_id_str: str,
    base_url: str,
    provider_factory: Optional[str],
    raw_models: Any,
) -> Dict[str, ModelCatalogProfile]:
    """Normalize the raw ``models`` mapping of one provider into profiles."""
    normalized_models: Dict[str, ModelCatalogProfile] = {}
    if not isinstance(raw_models, dict):
        return normalized_models
    for model_name, model_raw in raw_models.items():
        if not isinstance(model_raw, dict):
            continue
        model_name_str = str(model_name).strip()
        if not model_name_str:
            continue
        try:
            profile = _build_model_profile(
                provider_base_url=base_url,
                provider_factory=provider_factory,
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
    return normalized_models


def _normalize_provider(provider_id: Any, provider_raw: Any) -> Optional[Dict[str, Any]]:
    """Normalize one raw provider entry; returns None when it must be skipped."""
    if not isinstance(provider_raw, dict):
        return None
    provider_id_str = str(provider_id).strip()
    if not provider_id_str:
        return None

    display_name = str(provider_raw.get("display_name") or provider_id_str)
    base_url = str(provider_raw.get("base_url") or "").strip()
    provider_factory = _raw_nonempty_str(provider_raw, "model_factory")

    return {
        "display_name": display_name,
        "base_url": base_url,
        "model_factory": provider_factory,
        "models": _normalize_provider_models(
            provider_id_str, base_url, provider_factory, provider_raw.get("models")
        ),
    }


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
        normalized = _normalize_provider(provider_id, provider_raw)
        if normalized is not None:
            normalized_providers[str(provider_id).strip()] = normalized

    return {
        "version": version,
        "metadata": metadata,
        "providers": normalized_providers,
    }


def _raw_positive_int(raw: Dict[str, Any], key: str) -> Optional[int]:
    """Read a positive int from a raw catalog mapping; None when absent/invalid."""
    value = raw.get(key)
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _raw_bool(raw: Dict[str, Any], key: str, default: bool = False) -> bool:
    """Read a boolean from a raw catalog mapping, accepting common spellings."""
    value = raw.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("1", "true", "yes", "y", "on")
    return default


def _raw_nonempty_str(raw: Dict[str, Any], key: str) -> Optional[str]:
    """Read a stripped non-empty string from a raw catalog mapping."""
    value = raw.get(key)
    if not value:
        return None
    return str(value).strip()


def _raw_forced_temperature(raw: Dict[str, Any]) -> Optional[float]:
    """Read the provider-enforced sampling temperature from a raw catalog mapping."""
    value = raw.get("forced_temperature")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


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

    # Embedding models carry vector dimension in the legacy "max_tokens" column.
    # ``ModelCatalogProfile`` doesn't alias the column directly; the service
    # layer maps ``dimension`` -> ``max_tokens`` for embedding rows.

    return ModelCatalogProfile(
        model_type=model_type,
        display_name=display_name,
        base_url=base_url or None,
        model_factory=model_factory or None,
        context_window_tokens=_raw_positive_int(raw, "context_window_tokens"),
        max_input_tokens=_raw_positive_int(raw, "max_input_tokens"),
        max_output_tokens=_raw_positive_int(raw, "max_output_tokens"),
        default_output_reserve_tokens=_raw_positive_int(raw, "default_output_reserve_tokens"),
        tokenizer_family=_raw_nonempty_str(raw, "tokenizer_family"),
        expected_chunk_size=_raw_positive_int(raw, "expected_chunk_size"),
        maximum_chunk_size=_raw_positive_int(raw, "maximum_chunk_size"),
        chunk_batch=_raw_positive_int(raw, "chunk_batch"),
        dimension=_raw_positive_int(raw, "dimension"),
        timeout_seconds=_raw_positive_int(raw, "timeout_seconds"),
        concurrency_limit=_raw_positive_int(raw, "concurrency_limit"),
        capability_profile_version=_raw_nonempty_str(raw, "capability_profile_version"),
        reasoning_capability=raw.get("reasoning_capability"),
        requires_appid=_raw_bool(raw, "requires_appid"),
        requires_access_token=_raw_bool(raw, "requires_access_token"),
        forced_temperature=_raw_forced_temperature(raw),
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
        # The catalog version is intentionally NOT logged here: it is read
        # from an operator-supplied file and logging it verbatim would allow
        # forged log entries (S5144). The version is still observable through
        # the /catalog endpoints' JSON response.
        logger.info(
            "Model catalog loaded: providers=%d, models=%d",
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
    profile = models.get(str(model_name).strip())
    if profile is None:
        return None
    return _enrich_catalog_profile_reasoning(provider_id, str(model_name).strip(), profile)


def _enrich_catalog_profile_reasoning(
    provider_id: str,
    model_name: str,
    profile: ModelCatalogProfile,
) -> ModelCatalogProfile:
    """Overlay build-time models.dev reasoning metadata on a static profile.

    The operator-maintained catalog remains the source for capacity and other
    defaults.  Reasoning controls are resolved from the provider API and model
    ID in the build-time snapshot so newly released models do not depend on a
    second, stale static capability declaration.
    """
    models_dev_catalog = _load_models_dev_catalog()
    if models_dev_catalog is None:
        return profile

    capability = _resolve_models_dev_reasoning_capability(
        models_dev_catalog,
        model_name,
        profile.base_url,
        profile.model_factory or provider_id,
    )
    if capability is None:
        return profile
    profile_data = profile.model_dump(mode="python")
    profile_data["reasoning_capability"] = capability
    return ModelCatalogProfile.model_validate(profile_data)


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
        profile = _enrich_catalog_profile_reasoning(provider_id, model_name, profile)
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


def _canonical_api_url(value: Any) -> str:
    """Normalize an API URL for exact provider matching."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        if parsed.scheme and parsed.netloc:
            return urlunsplit(
                (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", "")
            )
    except ValueError:
        pass
    return raw.rstrip("/").lower()


def _model_id_candidates(model_key: Any, model_raw: Dict[str, Any]) -> List[str]:
    """Return model IDs exposed by one models.dev model record."""
    candidates = [model_key, model_raw.get("id"), model_raw.get("model")]
    result: List[str] = []
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value and value.lower() not in {item.lower() for item in result}:
            result.append(value)
    return result


def _normalize_reasoning_options(raw_options: Any) -> List[Dict[str, Any]]:
    """Normalize models.dev reasoning_options object/array variants."""
    if isinstance(raw_options, dict):
        if isinstance(raw_options.get("type"), str):
            raw_options = [raw_options]
        else:
            expanded: List[Dict[str, Any]] = []
            for option_type, option_value in raw_options.items():
                if isinstance(option_value, dict):
                    expanded.append({"type": option_type, **option_value})
                elif isinstance(option_value, list):
                    expanded.append({"type": option_type, "values": option_value})
            raw_options = expanded
    elif isinstance(raw_options, list):
        if all(isinstance(item, str) for item in raw_options):
            raw_options = [{"type": "effort", "values": raw_options}]
    else:
        raw_options = []

    return [item for item in raw_options if isinstance(item, dict)]


def _resolve_models_dev_reasoning_capability(
    catalog: Dict[str, Any],
    model_name: str,
    base_url: Optional[str],
    provider_hint: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Resolve one model by API first and model ID second."""
    requested_api = _canonical_api_url(base_url)
    requested_id = str(model_name or "").strip().lower()
    requested_leaf = requested_id.rsplit("/", 1)[-1]
    requested_provider = str(provider_hint or "").strip().lower()

    provider_candidates: List[tuple[str, Dict[str, Any]]] = []
    for provider_id, provider_raw in (catalog.get("providers") or {}).items():
        if not isinstance(provider_raw, dict):
            continue
        provider_api = _canonical_api_url(provider_raw.get("api") or provider_raw.get("base_url"))
        if requested_api:
            if provider_api == requested_api:
                provider_candidates.append((str(provider_id), provider_raw))
        elif requested_provider and str(provider_id).lower() == requested_provider:
            provider_candidates.append((str(provider_id), provider_raw))

    # API is the trust boundary. Do not search another provider when an API was
    # supplied but its model ID is absent from the source snapshot.
    if not provider_candidates:
        return None

    selected: Optional[tuple[str, str, Dict[str, Any]]] = None
    for provider_id, provider_raw in provider_candidates:
        raw_models = provider_raw.get("models")
        if not isinstance(raw_models, dict):
            continue
        for model_key, model_raw in raw_models.items():
            if not isinstance(model_raw, dict):
                continue
            ids = _model_id_candidates(model_key, model_raw)
            lowered_ids = {item.lower() for item in ids}
            if requested_id in lowered_ids:
                selected = (provider_id, ids[0], model_raw)
                break
            if requested_leaf and requested_leaf in {item.rsplit("/", 1)[-1].lower() for item in ids}:
                selected = (provider_id, ids[0], model_raw)
                break
        if selected:
            break

    if selected is None:
        return None

    provider_id, matched_model_id, model_raw = selected
    if model_raw.get("reasoning") is not True:
        return None
    options = _normalize_reasoning_options(model_raw.get("reasoning_options"))
    controls: List[Dict[str, Any]] = []
    effort_values: List[str] = []
    budget_range: Optional[Dict[str, int]] = None
    has_toggle = False
    for option in options:
        option_type = str(option.get("type") or "").strip().lower()
        if option_type == "toggle":
            has_toggle = True
        elif option_type == "effort":
            values = option.get("values") or option.get("options") or []
            if isinstance(values, str):
                values = [values]
            effort_values.extend(
                str(value).strip() for value in values
                if str(value).strip() and str(value).strip() not in effort_values
            )
        elif option_type == "budget_tokens":
            min_value = option.get("min", option.get("min_tokens", option.get("minimum")))
            max_value = option.get("max", option.get("max_tokens", option.get("maximum")))
            try:
                # models.dev uses zero as the lower bound for some providers.
                min_value = 0 if min_value is None else int(min_value)
                max_value = int(max_value)
            except (TypeError, ValueError):
                continue
            if min_value >= 0 and max_value >= min_value:
                budget_range = {"min": min_value, "max": max_value}

    if has_toggle:
        controls.append({"type": "toggle"})
    if effort_values:
        controls.append({"type": "effort", "values": effort_values})
    if budget_range:
        controls.append({"type": "budget_tokens", **budget_range})
    if not controls:
        return None

    if effort_values:
        legacy_levels = [value for value in effort_values if value in {
            "none", "minimal", "low", "medium", "high", "xhigh", "max"
        }]
        control = "effort"
        wire_format = "reasoning_effort"
    elif budget_range:
        legacy_levels = []
        control = "budget_tokens"
        wire_format = "thinking_budget"
    else:
        legacy_levels = []
        control = "toggle"
        wire_format = "thinking_toggle"

    return {
        "status": "supported",
        "control": control,
        "levels": legacy_levels,
        "default": "auto",
        "wire_format": wire_format,
        "effort_budgets": {},
        "controls": controls,
        "matched_api": _canonical_api_url(
            next(
                provider.get("api") or provider.get("base_url")
                for pid, provider in provider_candidates
                if pid == provider_id
            )
        ),
        "matched_model_id": matched_model_id,
        "source": "models_dev",
    }

#: Ordered candidates; first match wins.  The tuple is (provider_id, url_keyword).
_PROVIDER_URL_HINTS: Iterable[tuple[str, str]] = (
    ("silicon", "siliconflow"),
    ("silicon", "silicon"),
    ("dashscope", "aliyuncs"),
    ("dashscope", "dashscope"),
    ("tokenpony", "tokenpony"),
    ("volcengine", "volces"),
    ("volcengine", "volcengine"),
    ("deepseek", "api.deepseek.com"),
    ("zhipu", "open.bigmodel.cn"),
    ("anthropic", "api.anthropic.com"),
    ("google", "generativelanguage.googleapis.com"),
    ("mistral", "api.mistral.ai"),
    ("xai", "api.x.ai"),
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


def resolve_reasoning_capability(
    model_name: str,
    base_url: Optional[str] = None,
    provider_hint: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Resolve reasoning capability from an exact profile or safe ID family.

    Exact catalog entries are authoritative.  When an older/custom row is not
    an exact key, deterministic vendor/model-ID rules cover known families so
    newly released IDs do not lose the selector until the catalog is updated.
    Unknown IDs still return ``None``.
    """
    if not model_name:
        return None

    models_dev_catalog = _load_models_dev_catalog()
    if models_dev_catalog is not None:
        return _resolve_models_dev_reasoning_capability(
            models_dev_catalog,
            model_name,
            base_url,
            provider_hint,
        )

    provider_id = str(provider_hint or "").strip()
    if not get_provider_info(provider_id):
        provider_id = infer_provider_from_base_url(str(base_url or "")) or ""
    model_name_lower = str(model_name).strip().lower()
    model_leaf = model_name_lower.rsplit("/", 1)[-1]

    # A provider factory is not always persisted for older/custom rows. Infer
    # the vendor from the model id before falling back to an OpenAI-compatible
    # URL. This keeps historical rows discoverable after the catalog grows.
    if not provider_id:
        provider_id = _infer_provider_from_model_id(model_leaf) or ""

    inferred_provider = _infer_provider_from_model_id(model_leaf)

    if provider_id:
        profile = get_model_profile(provider_id, model_name)
        if profile is not None:
            # An explicit catalog entry without reasoning metadata is an
            # intentional unsupported declaration; do not override it with a
            # broad name heuristic.
            if profile.reasoning_capability is None:
                return None
            return profile.reasoning_capability.model_dump(mode="json")

    heuristic_provider = provider_id
    if provider_id in {
        "",
        "custom",
        "OpenAI-API-Compatible",
        "silicon",
        "modelengine",
    } and inferred_provider:
        heuristic_provider = inferred_provider
    return _infer_reasoning_capability_from_model_id(model_leaf, heuristic_provider)


def _infer_provider_from_model_id(model_id: str) -> Optional[str]:
    """Infer a known vendor from a model id when an old row lacks provider data."""
    value = str(model_id or "").lower()
    if "deepseek" in value:
        return "deepseek"
    if "claude" in value:
        return "anthropic"
    if "gemini" in value:
        return "google"
    if "grok" in value:
        return "xai"
    if re.match(r"^(?:o[1-4](?:[-.]|$)|gpt-5(?:[-.]|$))", value):
        return "openai"
    if re.match(r"^(?:glm|chatglm)[-_]", value):
        return "zhipu"
    if "qwen" in value or "qwq" in value:
        return "dashscope"
    if "mistral" in value or "magistral" in value:
        return "mistral"
    return None


def _reasoning_effort_capability(
    levels: List[str], default: str, wire_format: str = "reasoning_effort"
) -> Dict[str, Any]:
    return {
        "status": "supported",
        "control": "effort",
        "levels": levels,
        "default": default,
        "wire_format": wire_format,
        "source": "operator",
    }


def _resolve_deepseek_reasoning(value: str) -> Optional[Dict[str, Any]]:
    if re.search(r"deepseek[-_]?v4", value) or "deepseek-reasoner" in value:
        return _reasoning_effort_capability(["low", "high", "max"], "high")
    return None


def _resolve_zhipu_reasoning(value: str) -> Optional[Dict[str, Any]]:
    if re.match(r"(?:glm|chatglm)[-_]?(?:4\.[5-9]|5)", value):
        return {
            "status": "supported",
            "control": "toggle",
            "levels": ["none", "high"],
            "default": "high",
            "wire_format": "thinking_toggle",
            "source": "operator",
        }
    return None


def _resolve_anthropic_reasoning(value: str) -> Optional[Dict[str, Any]]:
    if re.search(r"claude[-_].*4", value):
        return _reasoning_effort_capability(
            ["none", "low", "medium", "high"], "medium", "thinking_budget"
        ) | {"effort_budgets": {"low": 2048, "medium": 8192, "high": 16384}}
    return None


def _resolve_google_reasoning(value: str) -> Optional[Dict[str, Any]]:
    if re.search(r"gemini[-_](?:2\.5|3|4)", value):
        return _reasoning_effort_capability(["low", "medium", "high"], "high")
    return None


def _resolve_openai_reasoning(value: str) -> Optional[Dict[str, Any]]:
    if re.match(r"(?:o[1-4]|gpt-5)(?:[-.]|$)", value):
        levels = (
            ["low", "medium", "high"]
            if value.startswith("o")
            else ["minimal", "low", "medium", "high"]
        )
        return _reasoning_effort_capability(levels, "medium")
    return None


def _resolve_xai_reasoning(value: str) -> Optional[Dict[str, Any]]:
    if re.match(r"grok[-_]4", value):
        return _reasoning_effort_capability(["low", "medium", "high", "xhigh"], "high")
    return None


def _resolve_qwen_reasoning(value: str) -> Optional[Dict[str, Any]]:
    if re.search(r"qwen[-_]?3", value) or "qwq" in value:
        return _reasoning_effort_capability(["low", "medium", "xhigh"], "medium")
    return None


def _resolve_mistral_reasoning(value: str) -> Optional[Dict[str, Any]]:
    if re.search(r"(?:magistral|mistral[-_]medium|mistral[-_]large)", value):
        return _reasoning_effort_capability(["none", "high"], "high")
    return None


_REASONING_CAPABILITY_RESOLVERS = {
    "deepseek": _resolve_deepseek_reasoning,
    "zhipu": _resolve_zhipu_reasoning,
    "anthropic": _resolve_anthropic_reasoning,
    "google": _resolve_google_reasoning,
    "openai": _resolve_openai_reasoning,
    "xai": _resolve_xai_reasoning,
    "dashscope": _resolve_qwen_reasoning,
    "silicon": _resolve_qwen_reasoning,
    "modelengine": _resolve_qwen_reasoning,
    "mistral": _resolve_mistral_reasoning,
}


def _infer_reasoning_capability_from_model_id(
    model_id: str,
    provider_id: str,
) -> Optional[Dict[str, Any]]:
    """Return a conservative capability for recognized model-id families.

    Exact catalog entries always win. This fallback is for provider model IDs
    introduced after the bundled catalog version and for historical custom
    rows whose provider/model name was not an exact catalog key.
    """
    value = str(model_id or "").lower()
    resolver = _REASONING_CAPABILITY_RESOLVERS.get(str(provider_id or "").lower())
    return resolver(value) if resolver else None


# ---------------------------------------------------------------------------
# Apply catalog defaults to user model_data (used by service layer)
# ---------------------------------------------------------------------------


def _is_empty_value(value: Any) -> bool:
    """0 / False are allowed for int/bool flags; treat None / "" as empty."""
    if value is None:
        return True
    return isinstance(value, str) and value.strip() == ""


# Mapping: target field on model_data -> source field on profile.
# Rationale: keep ModelCatalogProfile focused; map legacy aliases here so
# the catalog schema stays stable.
_CATALOG_DEFAULT_FIELD_MAP: Dict[str, str] = {
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
    # Provider-enforced sampling temperature (reasoning-only models). Only
    # fills when the user has not set a temperature themselves.
    "temperature": "forced_temperature",
}


def _apply_field_defaults(model_data: Dict[str, Any], profile_dict: Dict[str, Any]) -> bool:
    """Fill every empty target field from the profile; True when any value applied."""
    applied = False
    for target, source in _CATALOG_DEFAULT_FIELD_MAP.items():
        if _is_empty_value(model_data.get(target)):
            catalog_value = profile_dict.get(source)
            if catalog_value is not None and catalog_value != "":
                model_data[target] = catalog_value
                applied = True
    return applied


def _apply_special_defaults(model_data: Dict[str, Any], profile: ModelCatalogProfile) -> bool:
    """Apply the non-field-map defaults: embedding dimension and STT/TTS hints."""
    applied = False
    # Special: embedding vector dimension -> legacy max_tokens column.
    # The existing service layer already sets max_tokens from dimension for
    # embedding records; duplicating here is safe because we only fill when
    # the target is empty.
    if profile.dimension and _is_empty_value(model_data.get("max_tokens")):
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
    return applied


def _resolve_catalog_profile(
    model_data: Dict[str, Any],
    provider_hint: Optional[str],
) -> Optional[ModelCatalogProfile]:
    """Locate the catalog profile for a model_data row; None when unresolvable."""
    if not provider_hint:
        provider_hint = infer_provider_from_base_url(
            str(model_data.get("base_url") or "")
        )
    if not provider_hint:
        return None

    model_name = str(model_data.get("model_name") or "").strip()
    if not model_name:
        return None

    return get_model_profile(provider_hint, model_name)


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

    profile = _resolve_catalog_profile(model_data, provider_hint)
    if profile is None:
        return False

    applied = _apply_field_defaults(model_data, profile.model_dump())
    applied = _apply_special_defaults(model_data, profile) or applied

    if applied and not model_data.get("capacity_source"):
        # Tag capacity_source = "profile" only if the caller didn't already set one.
        model_data["capacity_source"] = "profile"
    return applied
