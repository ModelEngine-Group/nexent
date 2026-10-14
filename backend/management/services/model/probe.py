"""Model endpoint normalization and embedding dimension probes."""

import logging
from typing import Any, Dict, List, Optional, Tuple

from consts.const import DOCKER_INTERNAL_HOST, LOCALHOST_IP, LOCALHOST_NAME
from management.services.model.adapter import build_adapter_fresh
from management.services.model.names import get_model_name_from_config

logger = logging.getLogger("model_health_service")
DASHSCOPE_MODEL_FACTORY = "dashscope"
TOKENPONY_MODEL_FACTORY = "tokenpony"
SILICONFLOW_MODEL_FACTORY = "silicon"
EMBEDDING_TYPES = {"embedding", "multi_embedding"}


def _normalize_embedding_url(base_url: str) -> str:
    """Append /embeddings suffix to base_url if not already present.

    For embedding and multimodal embedding models, the base_url should contain /embeddings.
    If the user provides a base URL without the endpoint (e.g., https://api.jina.ai/v1),
    this function normalizes it to include /embeddings (e.g., https://api.jina.ai/v1/embeddings).
    """
    if not base_url or "/embeddings" in base_url:
        return base_url
    return f"{base_url.rstrip('/')}/embeddings"


def _embedding_url_candidates(base_url: str) -> List[str]:
    """Ordered URLs to probe: the /embeddings endpoint first, then the URL as given."""
    if not base_url:
        return []
    normalized = _normalize_embedding_url(base_url)
    return [normalized] if normalized == base_url else [normalized, base_url]


def _infer_model_factory(
    model_type: str, base_url: str, current_factory: Optional[str] = None
) -> Optional[str]:
    """Infer model_factory from base_url if not already set or is generic.

    For embedding/multi_embedding, recognizes dashscope and siliconflow URLs.
    For other types (VLM), uses extended inference so tokenpony URLs can be
    recognized for catalog healthcheck.
    """
    # Embedding types: infer from base_url host
    if model_type in EMBEDDING_TYPES:
        if "dashscope" in base_url.lower():
            return DASHSCOPE_MODEL_FACTORY
        if "siliconflow" in base_url.lower():
            return (
                SILICONFLOW_MODEL_FACTORY  # stored as "silicon" for catalog consistency
            )
        return current_factory

    # Non-embedding types (VLM, etc): use extended inference
    try:
        from management.services.model.capacity import pick_provider_from_base_url

        inferred_provider = pick_provider_from_base_url(base_url)
    except Exception:
        inferred_provider = (
            DASHSCOPE_MODEL_FACTORY if "dashscope" in base_url.lower() else None
        )

    if inferred_provider:
        return inferred_provider

    return current_factory


async def _embedding_dimension_check(
    model_name: str,
    model_type: str,
    model_base_url: str,
    model_api_key: str,
    ssl_verify: bool = True,
    model_factory: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    extra_params: Optional[dict] = None,
):
    effective_timeout = timeout_seconds if timeout_seconds else 5.0

    if model_type == "embedding":
        adapter_config = {
            "base_url": model_base_url,
            "api_key": model_api_key,
            "ssl_verify": ssl_verify,
            "model_type": "embedding",
        }
        if extra_params is not None:
            adapter_config["extra_params"] = extra_params
        embedding = await build_adapter_fresh(
            adapter_config,
            "embedding",
            "embedding",
            None,
            model_name=model_name,
        ).dimension_check(timeout=effective_timeout)
        if len(embedding) > 0:
            return len(embedding[0])
        logging.warning(
            f"Embedding dimension check for {model_name} gets empty response"
        )
        return 0
    elif model_type == "multi_embedding":
        adapter_config = {
            "model_factory": model_factory,
            "base_url": model_base_url,
            "api_key": model_api_key,
            "ssl_verify": ssl_verify,
            "model_type": "multi_embedding",
        }
        if extra_params is not None:
            adapter_config["extra_params"] = extra_params
        embedding = await build_adapter_fresh(
            adapter_config,
            "multi_embedding",
            "multiEmbedding",
            None,
            model_name=model_name,
        ).dimension_check(timeout=effective_timeout)
        if (
            isinstance(embedding, list)
            and len(embedding) > 0
            and isinstance(embedding[0], list)
        ):
            return len(embedding[0])
        logging.warning(
            f"Embedding dimension check for {model_name} gets unexpected response: {type(embedding)}, value: {embedding}"
        )
        return 0
    else:
        raise ValueError(f"Unsupported model type: {model_type}")


async def embedding_dimension_check(model_config: dict):
    model_name = get_model_name_from_config(model_config)
    model_type = model_config["model_type"]
    model_base_url = model_config["base_url"]
    model_api_key = model_config["api_key"]

    try:
        ssl_verify = model_config.get("ssl_verify", True)
        model_factory = _infer_model_factory(
            model_type, model_base_url, model_config.get("model_factory")
        )
        timeout_seconds = model_config.get("timeout_seconds")
        embedding_check_kwargs = {
            "model_factory": model_factory,
            "timeout_seconds": timeout_seconds,
        }
        if model_config.get("extra_params") is not None:
            embedding_check_kwargs["extra_params"] = model_config["extra_params"]
        dimension = await _embedding_dimension_check(
            model_name,
            model_type,
            model_base_url,
            model_api_key,
            ssl_verify,
            **embedding_check_kwargs,
        )
        # Fallback to ssl_verify=False if initial check fails
        if dimension == 0 and ssl_verify:
            dimension = await _embedding_dimension_check(
                model_name,
                model_type,
                model_base_url,
                model_api_key,
                False,
                **embedding_check_kwargs,
            )
        if dimension == 0:
            logger.error(
                f"Embedding dimension check returned 0 for model: {model_name}"
            )
            return None
        return dimension
    except ValueError as e:
        logger.error(f"Error checking embedding dimension for {model_name}: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Error checking embedding dimension for {model_name}: {str(e)}")
        return None


async def resolve_embedding_base_url(
    model_data: Dict[str, Any],
) -> Tuple[Optional[str], Optional[int]]:
    """Return the first candidate URL that served embeddings, plus its dimension.

    Returns (None, None) when no candidate answered.
    """
    base_url = model_data.get("base_url") or ""
    if LOCALHOST_NAME in base_url or LOCALHOST_IP in base_url:
        base_url = base_url.replace(LOCALHOST_NAME, DOCKER_INTERNAL_HOST).replace(
            LOCALHOST_IP, DOCKER_INTERNAL_HOST
        )
    for candidate_url in _embedding_url_candidates(base_url):
        dimension = await embedding_dimension_check(
            {**model_data, "base_url": candidate_url}
        )
        if dimension is not None:
            return candidate_url, dimension
    return None, None
