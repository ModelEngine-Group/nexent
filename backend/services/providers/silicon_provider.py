import httpx
from typing import Dict, List

from consts.const import DEFAULT_LLM_MAX_TOKENS
from consts.provider import SILICON_GET_URL
from services.providers.base import AbstractModelProvider, _classify_provider_error


class SiliconModelProvider(AbstractModelProvider):
    """Concrete implementation for SiliconFlow provider."""

    async def get_models(self, provider_config: Dict) -> List[Dict]:
        """
        Fetch models from SiliconFlow API.

        Args:
            provider_config: Configuration dict containing model_type and api_key

        Returns:
            List of models with canonical fields. Returns error dict if API call fails.
        """
        try:
            model_type: str = provider_config["model_type"]
            model_api_key: str = provider_config["api_key"]

            headers = {"Authorization": f"Bearer {model_api_key}"}

            # Choose endpoint by model type
            if model_type in ("llm", "vlm"):
                silicon_url = f"{SILICON_GET_URL}?sub_type=chat"
            elif model_type in ("embedding", "multi_embedding"):
                silicon_url = f"{SILICON_GET_URL}?sub_type=embedding"
            else:
                silicon_url = SILICON_GET_URL

            async with httpx.AsyncClient(verify=False) as client:
                response = await client.get(silicon_url, headers=headers)
                response.raise_for_status()
                model_list: List[Dict] = response.json()["data"]

            # Annotate models with canonical fields expected downstream
            if model_type in ("llm", "vlm"):
                for item in model_list:
                    item["model_tag"] = "chat"
                    item["model_type"] = model_type
                    item["max_tokens"] = DEFAULT_LLM_MAX_TOKENS
            elif model_type in ("embedding", "multi_embedding"):
                for item in model_list:
                    item["model_tag"] = "embedding"
                    item["model_type"] = model_type

            # Return empty list to indicate successful API call but no models
            if not model_list:
                return []

            return model_list
        except (httpx.HTTPStatusError, httpx.ConnectTimeout, httpx.ConnectError, Exception) as e:
            return _classify_provider_error("SiliconFlow", exception=e)
