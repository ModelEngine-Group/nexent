import logging
from typing import Dict, List

import aiohttp

from consts.const import DEFAULT_LLM_MAX_TOKENS
from services.providers.base import AbstractModelProvider, _classify_provider_error

logger = logging.getLogger("model_provider")

MODEL_ENGINE_NORTH_PREFIX = "open/router/v1"


def get_model_engine_raw_url(model_engine_url: str) -> str:
    """
    Extract the raw base URL from a ModelEngine URL by stripping any API paths.

    Args:
        model_engine_url: Full ModelEngine URL potentially containing API paths

    Returns:
        Base URL without trailing paths
    """
    if not model_engine_url:
        return ""
    # Remove any trailing /open/router/v1 or similar paths to get base host
    raw_url = model_engine_url.split(
        "/open/")[0] if "/open/" in model_engine_url else model_engine_url
    # Remove trailing slash if present
    return raw_url.rstrip('/')


class ModelEngineProvider(AbstractModelProvider):
    """Concrete implementation for ModelEngine provider."""

    async def get_models(self, provider_config: Dict) -> List[Dict]:
        """
        Fetch models from ModelEngine API.

        Args:
            provider_config: Configuration dict containing model_type, base_url, and api_key

        Returns:
            List of models with canonical fields. Returns error dict if API call fails.
        """
        try:
            model_type: str = provider_config.get("model_type", "")
            host = provider_config.get("base_url")
            api_key = provider_config.get("api_key")
            model_engine_url = get_model_engine_raw_url(host)
            if not host or not api_key:
                logger.warning("ModelEngine host or api key not configured")
                return []

            headers = {"Authorization": f"Bearer {api_key}"}

            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                connector=aiohttp.TCPConnector(ssl=False)
            ) as session:
                async with session.get(
                    f"{model_engine_url.rstrip('/')}/{MODEL_ENGINE_NORTH_PREFIX}/models",
                    headers=headers
                ) as response:
                    # Use centralized error classification
                    if response.status >= 400:
                        error_text = await response.text()
                        return _classify_provider_error(
                            "ModelEngine",
                            status_code=response.status,
                            error_message=error_text
                        )

                    data = await response.json()
                    all_models = data.get("data", [])
                    logger.info(
                        f"ModelEngine API returned {len(all_models)} models")

            # Type mapping from ModelEngine to internal types
            type_map = {
                "embed": "embedding",
                "chat": "llm",
                "asr": "stt",
                "tts": "tts",
                "rerank": "rerank",
                "multimodal": "vlm",
            }

            filtered_models = []
            for model in all_models:
                me_type = model.get("type", "")
                internal_type = type_map.get(me_type)

                # If model_type filter is provided, only include matching models
                if model_type and internal_type != model_type:
                    continue

                if internal_type:
                    filtered_models.append({
                        "id": model.get("id", ""),
                        "model_type": internal_type,
                        "model_tag": me_type,
                        "max_tokens": DEFAULT_LLM_MAX_TOKENS if internal_type in ("llm", "vlm") else 0,
                        "base_url": host,
                        "api_key": api_key,
                    })

            return filtered_models
        except Exception as e:
            return _classify_provider_error("ModelEngine", exception=e)
