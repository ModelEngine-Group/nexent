from typing import Dict, List

import httpx
from consts.const import DEFAULT_LLM_MAX_TOKENS
from consts.provider import ORCAROUTER_GET_URL
from services.providers.base import (
    AbstractModelProvider,
    _classify_provider_error,
    _extract_capacity_hints_from_raw,
)


# OrcaRouter is a chat-only gateway. The /v1/models catalog only carries
# models that support chat (the gateway routes to upstream LLMs on demand).
# Model IDs all use the ``orcarouter/`` namespace prefix (e.g.
# ``orcarouter/auto``, ``orcarouter/fusion``).
ORCAROUTER_CHAT_TYPES = ("llm", "vlm")


def _extract_capacity_hints(raw: Dict) -> Dict:
    return _extract_capacity_hints_from_raw(raw)


class OrcaRouterModelProvider(AbstractModelProvider):
    """Concrete implementation for the OrcaRouter model gateway.

    OrcaRouter is an OpenAI-compatible gateway: the chat model catalog is
    fetched from ``GET /v1/models`` and every model routes through the
    gateway's smart router (default model ``orcarouter/auto``).
    """

    async def get_models(self, provider_config: Dict) -> List[Dict]:
        """
        Fetch chat models from the OrcaRouter gateway API.

        Args:
            provider_config: Configuration dict containing model_type and api_key

        Returns:
            List of chat models with canonical fields. Returns error dict if
            the API call fails.
        """
        try:
            model_type: str = provider_config["model_type"]
            model_api_key: str = provider_config["api_key"]

            # OrcaRouter only routes chat models; non-chat modalities have no
            # gateway endpoints (e.g. /v1/embeddings returns 400).
            if model_type not in ORCAROUTER_CHAT_TYPES:
                return []

            headers = {"Authorization": f"Bearer {model_api_key}"}

            async with httpx.AsyncClient() as client:
                response = await client.get(ORCAROUTER_GET_URL, headers=headers)
                response.raise_for_status()
                # OpenAI-standard response: model list under the "data" array
                all_models: List[Dict] = response.json().get("data", [])

            models = []
            for model_obj in all_models:
                model_id = model_obj.get("id", "")
                cleaned_model = {
                    "id": model_id,
                    "model_tag": "chat",
                    "model_type": model_type,
                    "max_tokens": DEFAULT_LLM_MAX_TOKENS,
                }
                cleaned_model.update(_extract_capacity_hints(model_obj))
                models.append(cleaned_model)

            return models
        except (httpx.HTTPStatusError, httpx.ConnectTimeout, httpx.ConnectError, Exception) as e:
            status_code = e.response.status_code if isinstance(e, httpx.HTTPStatusError) and getattr(e, "response", None) else None
            return _classify_provider_error(
                "OrcaRouter",
                status_code=status_code,
                error_message=str(e),
                exception=e,
            )
