import logging
from typing import Dict, List

from consts.const import DEFAULT_LLM_MAX_TOKENS
from services.providers.base import AbstractModelProvider, _classify_provider_error

logger = logging.getLogger("model_provider")


class LiteLLMModelProvider(AbstractModelProvider):
    """Provider that discovers models via LiteLLM's /v1/models endpoint.

    LiteLLM supports 100+ LLM providers (OpenAI, Anthropic, Google Gemini,
    Azure, Bedrock, Ollama, etc.) through a unified interface. When pointed
    at a LiteLLM proxy, this provider fetches the available model catalog.

    For direct SDK usage (no proxy), users should add models manually with
    the ``litellm`` provider and use LiteLLM model identifiers like
    ``anthropic/claude-sonnet-4-20250514`` or ``gemini/gemini-2.5-flash``.
    """

    async def get_models(self, provider_config: Dict) -> List[Dict]:
        """
        Fetch models from a LiteLLM-compatible /v1/models endpoint.

        Args:
            provider_config: Configuration dict containing model_type, api_key, and base_url

        Returns:
            List of models with canonical fields.
        """
        import httpx

        try:
            model_type: str = provider_config.get("model_type", "llm")
            api_key: str = provider_config.get("api_key", "")
            base_url: str = provider_config.get("base_url", "").rstrip("/")

            if not base_url:
                return []

            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            models_url = f"{base_url}/models"

            async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
                response = await client.get(models_url, headers=headers)
                response.raise_for_status()
                data = response.json().get("data", [])

            model_list = []
            for item in data:
                model_id = item.get("id", "")
                if not model_id:
                    continue

                model_entry = {
                    "id": model_id,
                    "model_type": model_type,
                    "max_tokens": DEFAULT_LLM_MAX_TOKENS,
                }

                if model_type in ("llm", "vlm"):
                    model_entry["model_tag"] = "chat"
                elif model_type in ("embedding", "multi_embedding"):
                    model_entry["model_tag"] = "embedding"
                elif model_type == "rerank":
                    model_entry["model_tag"] = "rerank"

                model_list.append(model_entry)

            return model_list

        except Exception as e:
            return _classify_provider_error("LiteLLM", exception=e)
