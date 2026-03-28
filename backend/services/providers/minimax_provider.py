import httpx
from typing import Dict, List

from consts.const import DEFAULT_LLM_MAX_TOKENS
from consts.provider import MINIMAX_GET_URL
from services.providers.base import AbstractModelProvider, _classify_provider_error


# MiniMax known model context windows (tokens)
MINIMAX_MODEL_CONTEXT = {
    "MiniMax-M2.7": 1000000,
    "MiniMax-M2.5": 204800,
    "MiniMax-M2.5-highspeed": 204800,
}


class MiniMaxModelProvider(AbstractModelProvider):
    """Concrete implementation for MiniMax provider."""

    async def get_models(self, provider_config: Dict) -> List[Dict]:
        """
        Fetch models from MiniMax API, categorize them based on model ID,
        and return the requested model type.

        Args:
            provider_config: Configuration dict containing model_type and api_key

        Returns:
            List of models with canonical fields. Returns error dict if API call fails.
        """
        try:
            target_model_type: str = provider_config["model_type"]
            model_api_key: str = provider_config["api_key"]

            headers = {"Authorization": f"Bearer {model_api_key}"}
            url = MINIMAX_GET_URL

            async with httpx.AsyncClient(verify=False) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                all_models: List[Dict] = response.json().get("data", [])

            # Initialize containers for the main categories
            categorized_models = {
                "chat": [],       # Maps to "llm"
                "vlm": [],        # Maps to "vlm"
                "embedding": [],  # Maps to "embedding" / "multi_embedding"
                "reranker": [],   # Maps to "reranker"
                "tts": [],        # Maps to "tts"
                "stt": []         # Maps to "stt"
            }

            for model_obj in all_models:
                m_id = model_obj.get("id", "")
                m_id_lower = m_id.lower()
                model_obj.setdefault("object", "model")
                model_obj.setdefault("owned_by", "minimax")

                # Use known context window or default
                max_tokens = MINIMAX_MODEL_CONTEXT.get(m_id, DEFAULT_LLM_MAX_TOKENS)

                cleaned_model = {
                    "id": m_id,
                    "object": model_obj.get("object"),
                    "created": model_obj.get("created", 0),
                    "owned_by": model_obj.get("owned_by"),
                    "model_tag": "",
                    "model_type": "",
                    "max_tokens": max_tokens,
                }

                # 1. Embedding
                if "embo" in m_id_lower or "embedding" in m_id_lower:
                    cleaned_model.update({"model_tag": "embedding", "model_type": "embedding"})
                    categorized_models["embedding"].append(cleaned_model)

                # 2. TTS (speech models)
                elif "speech" in m_id_lower or "tts" in m_id_lower:
                    cleaned_model.update({"model_tag": "tts", "model_type": "tts"})
                    categorized_models["tts"].append(cleaned_model)

                # 3. STT
                elif "stt" in m_id_lower or "whisper" in m_id_lower:
                    cleaned_model.update({"model_tag": "stt", "model_type": "stt"})
                    categorized_models["stt"].append(cleaned_model)

                # 4. Reranker
                elif "rerank" in m_id_lower:
                    cleaned_model.update({"model_tag": "reranker", "model_type": "reranker"})
                    categorized_models["reranker"].append(cleaned_model)

                # 5. VLM
                elif any(kw in m_id_lower for kw in ["-vl", "vl-", "vision"]):
                    cleaned_model.update({"model_tag": "chat", "model_type": "vlm"})
                    categorized_models["vlm"].append(cleaned_model)

                # 6. Chat / LLM (default fallback)
                else:
                    cleaned_model.update({"model_tag": "chat", "model_type": "llm"})
                    categorized_models["chat"].append(cleaned_model)

            # Return the specific list based on the requested target_model_type
            if target_model_type == "llm":
                return categorized_models["chat"]
            elif target_model_type in ("embedding", "multi_embedding"):
                return categorized_models["embedding"]
            elif target_model_type in categorized_models:
                return categorized_models[target_model_type]
            else:
                return []

        except (httpx.HTTPStatusError, httpx.ConnectTimeout, httpx.ConnectError, Exception) as e:
            return _classify_provider_error("MiniMax", exception=e)
