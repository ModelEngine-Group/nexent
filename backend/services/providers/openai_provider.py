"""Generic OpenAI-compatible provider.

Used as the fallback for any provider that is not covered by a dedicated
implementation (silicon / modelengine / dashscope / tokenpony).  It simply
calls the standard ``GET {base_url}/models`` endpoint and returns the raw
model list annotated with the canonical fields expected downstream.
"""

import logging
from typing import Dict, List

import httpx

from services.providers.base import (
    AbstractModelProvider,
    _classify_provider_error,
    _extract_capacity_hints_from_raw,
)

logger = logging.getLogger("model_provider")


class OpenAICompatibleProvider(AbstractModelProvider):
    """Fetch models from any OpenAI-compatible ``/v1/models`` endpoint."""

    async def get_models(self, provider_config: Dict) -> List[Dict]:
        try:
            model_api_key: str = provider_config["api_key"]
            base_url: str = provider_config.get("base_url", "") or ""

            # Normalise the base URL: strip trailing slashes, ensure it ends
            # with the ``/models`` path.
            url = base_url.rstrip("/")
            if not url.endswith("/models"):
                url = f"{url}/models"

            headers = {"Authorization": f"Bearer {model_api_key}"}

            async with httpx.AsyncClient(verify=False, timeout=30) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                payload = response.json()

            raw_list: List[Dict] = payload.get("data", [])
            if not isinstance(raw_list, list):
                raw_list = []

            # Annotate each model with canonical fields. model_type is left
            # empty here — the caller (create_provider_models_for_tenant)
            # infers it from the model name when model_type is not specified.
            model_list: List[Dict] = []
            for item in raw_list:
                if not isinstance(item, dict):
                    continue
                model_id = str(item.get("id", "")).strip()
                if not model_id:
                    continue
                annotated = {
                    "id": model_id,
                    "model_tag": "chat",
                }
                # Merge capacity hints if the provider included any.
                hints = _extract_capacity_hints_from_raw(item)
                annotated.update(hints)
                model_list.append(annotated)

            return model_list

        except (httpx.HTTPStatusError, httpx.ConnectTimeout, httpx.ConnectError, Exception) as e:
            if isinstance(e, httpx.HTTPStatusError):
                status_code = e.response.status_code
                error_message = str(e)
                return _classify_provider_error(
                    "OpenAI-compatible", status_code=status_code, error_message=error_message
                )
            return _classify_provider_error(
                "OpenAI-compatible", exception=e
            )
