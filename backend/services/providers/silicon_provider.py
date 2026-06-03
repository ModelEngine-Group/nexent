import httpx
import re
from typing import Dict, List

from consts.const import DEFAULT_LLM_MAX_TOKENS
from consts.provider import SILICON_GET_URL
from services.providers.base import AbstractModelProvider, _classify_provider_error


SILICON_VLM_MODEL_KEYWORDS = (
    "-vl",
    "_vl",
    "/vl",
    ".vl",
    "vl-",
    "vision",
    "visual",
    "internvl",
    "deepseek-vl",
    "deepseekvl",
    "glm-4v",
    "minicpm-v",
    "llava",
    "kimi-vl",
    "kimi-k2.5",
    "kimi-k2.6",
    "qvq",
    "omni",
    "qwen3.5",
    "qwen3.6",
)

SILICON_VLM_METADATA_KEYWORDS = ("image", "video", "vision", "visual")


def _contains_silicon_vlm_metadata(value) -> bool:
    if isinstance(value, str):
        lower_value = value.lower()
        return any(keyword in lower_value for keyword in SILICON_VLM_METADATA_KEYWORDS)
    if isinstance(value, list):
        return any(_contains_silicon_vlm_metadata(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_silicon_vlm_metadata(item) for item in value.values())
    return False


def _is_silicon_vlm_model(model: Dict) -> bool:
    if _contains_silicon_vlm_metadata(model):
        return True

    model_id = str(model.get("id", "")).lower()
    model_name = str(model.get("name", "")).lower()
    searchable_text = f"{model_id} {model_name}"
    if any(keyword in searchable_text for keyword in SILICON_VLM_MODEL_KEYWORDS):
        return True

    return bool(re.search(r"glm-\d+(?:\.\d+)?v", searchable_text))


def _is_silicon_omni_model(model: Dict) -> bool:
    model_id = str(model.get("id", "")).lower()
    model_name = str(model.get("name", "")).lower()
    return "omni" in f"{model_id} {model_name}"


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

            provider_model_type = "vlm" if model_type in ("vlm2", "vlm3") else model_type

            # Choose endpoint by model type
            if provider_model_type in ("llm", "vlm"):
                silicon_url = f"{SILICON_GET_URL}?sub_type=chat"
            elif provider_model_type in ("embedding", "multi_embedding"):
                silicon_url = f"{SILICON_GET_URL}?sub_type=embedding"
            elif provider_model_type == "rerank":
                silicon_url = f"{SILICON_GET_URL}?sub_type=reranker"
            else:
                return []

            async with httpx.AsyncClient(verify=False) as client:
                response = await client.get(silicon_url, headers=headers)
                response.raise_for_status()
                model_list: List[Dict] = response.json()["data"]

            if model_type == "vlm3":
                model_list = [item for item in model_list if _is_silicon_omni_model(item)]
            elif provider_model_type == "vlm":
                model_list = [item for item in model_list if _is_silicon_vlm_model(item)]

            # Annotate models with canonical fields expected downstream
            if provider_model_type in ("llm", "vlm"):
                for item in model_list:
                    item["model_tag"] = "chat"
                    item["model_type"] = model_type
                    item["max_tokens"] = DEFAULT_LLM_MAX_TOKENS
            elif provider_model_type in ("embedding", "multi_embedding"):
                for item in model_list:
                    item["model_tag"] = "embedding"
                    item["model_type"] = model_type
            elif provider_model_type == "rerank":
                for item in model_list:
                    item["model_tag"] = "rerank"
                    item["model_type"] = model_type

            # Return empty list to indicate successful API call but no models
            if not model_list:
                return []

            return model_list
        except (httpx.HTTPStatusError, httpx.ConnectTimeout, httpx.ConnectError, Exception) as e:
            return _classify_provider_error("SiliconFlow", exception=e)
