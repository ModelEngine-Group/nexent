import httpx
from typing import Dict, List
import asyncio
from consts.const import DEFAULT_LLM_MAX_TOKENS
from consts.provider import DASHSCOPE_GET_URL
from services.providers.base import AbstractModelProvider, _classify_provider_error


class DashScopeModelProvider(AbstractModelProvider):
    """Concrete implementation for DashScope (Aliyun) provider."""

    async def get_models(self, provider_config: Dict) -> List[Dict]:
        """
        Fetch models from DashScope API, categorize them, and return
        the requested model type.

        Args:
            provider_config: Configuration dict containing model_type and api_key

        Returns:
            List of models with canonical fields. Returns error dict if API call fails.
        """
        try:
            target_model_type: str = provider_config["model_type"]
            model_api_key: str = provider_config["api_key"]

            headers = {"Authorization": f"Bearer {model_api_key}"}
            base_url = DASHSCOPE_GET_URL

            all_models: List[Dict] = []
            current_page = 1

            # Fetch all models with pagination asynchronously
            async with httpx.AsyncClient(verify=False) as client:
                while True:
                    params = {"page_size": 100, "page_no": current_page}
                    response = await client.get(base_url, headers=headers, params=params)
                    response.raise_for_status()

                    data = response.json()
                    models = data.get("output", {}).get("models", [])

                    if response.status_code == 429:
                        await asyncio.sleep(2)
                        continue
                    if not models :  # Break loop if no more models on the current page
                        break

                    all_models.extend(models)
                    if(len(models)<100):
                        break
                    current_page += 1
                    await asyncio.sleep(0.5)

            # Initialize containers for the 6 main categories
            categorized_models = {
                "chat": [],  # Maps to "llm"
                "vlm": [],  # Maps to "vlm"
                "embedding": [],  # Maps to "embedding" / "multi_embedding"
                "reranker": [],  # Maps to "reranker"
                "tts": [],  # Maps to "tts"
                "stt": []  # Maps to "stt"
            }

            # Classify models and inject canonical fields expected downstream
            for model_obj in all_models:
                # Extract key fields for logical determination (lowercased for robustness)
                m_id = model_obj.get('model', '').lower()
                desc = model_obj.get('description', '')
                metadata = model_obj.get('inference_metadata', {})
                req_mod = metadata.get('request_modality', [])
                res_mod = metadata.get('response_modality', [])
                model_obj.setdefault("object", model_obj.get("object", "model"))
                model_obj.setdefault("owned_by", model_obj.get("owned_by", "dashscope"))
                cleaned_model = {
                    "id": m_id,
                    "object": model_obj.get("object"),
                    "created": 0,
                    "owned_by": model_obj.get("owned_by"),
                    "model_tag": "",
                    "model_type": "",
                    "max_tokens": DEFAULT_LLM_MAX_TOKENS
                }
               # 1. Embedding
                if 'embedding' in m_id.lower() or '向量' in desc:
                    cleaned_model.update({"model_tag": "embedding", "model_type": "embedding"})
                    categorized_models['embedding'].append(cleaned_model)
                    continue

                # 2. Reranker
                if 'rerank' in m_id.lower() or '重排序' in desc:
                    cleaned_model.update({"model_tag": "reranker", "model_type": "reranker"})
                    categorized_models['reranker'].append(cleaned_model)
                    continue

                # 3. STT
                if 'Audio' in req_mod and 'Text' in res_mod:
                    cleaned_model.update({"model_tag": "stt", "model_type": "stt"})
                    categorized_models['stt'].append(cleaned_model)
                    continue

                # 4. TTS
                if 'Audio' in res_mod and 'Video' not in res_mod:
                    cleaned_model.update({"model_tag": "tts", "model_type": "tts"})
                    categorized_models['tts'].append(cleaned_model)
                    continue

                # 5. VLM
                vision_mods = {'Image', 'Video'}
                if (set(req_mod) & vision_mods) or (set(res_mod) & vision_mods) or '视觉' in desc:
                    cleaned_model.update({"model_tag": "chat", "model_type": "vlm"})
                    categorized_models['vlm'].append(cleaned_model)
                    continue

                # 6. Chat / LLM
                if 'Text' in req_mod or 'Text' in res_mod:
                    cleaned_model.update({"model_tag": "chat", "model_type": "llm"})
                    categorized_models['chat'].append(cleaned_model)

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
            return _classify_provider_error("DashScope", exception=e)

