import httpx
from typing import Dict, List
import asyncio
from consts.const import DEFAULT_LLM_MAX_TOKENS
from consts.provider import DASHSCOPE_GET_URL
from services.providers.base import AbstractModelProvider, _classify_provider_error


DASHSCOPE_IMAGE_GENERATION_KEYWORDS = (
    "image",
    "wanx",
    "aitryon",
    "tryon",
    "flux",
    "stable-diffusion",
    "sdxl",
)
DASHSCOPE_IMAGE_UNDERSTANDING_KEYWORDS = (
    "qwen-vl",
    "qwen2-vl",
    "qwen2.5-vl",
    "qwen3-vl",
    "qwen3.5-vl",
    "qwen3.6-vl",
    "-vl",
    "vl-",
    "vision",
    "visual",
    "ocr",
    "qwen3.6",
    "qwen-3.6",
)
DASHSCOPE_VIDEO_UNDERSTANDING_KEYWORDS = ("omni", "video-understanding", "video-ocr")


def _modality_set(value) -> set:
    if not value:
        return set()
    if isinstance(value, str):
        return {value.lower()}
    return {str(item).lower() for item in value}


def _has_keyword(text: str, keywords: tuple) -> bool:
    return any(keyword in text for keyword in keywords)


def _is_dashscope_explicit_image_understanding_model(model_id: str) -> bool:
    return _has_keyword(model_id, DASHSCOPE_IMAGE_UNDERSTANDING_KEYWORDS)


def _is_dashscope_image_generation_model(model_id: str, desc: str, req_mods: set, res_mods: set) -> bool:
    if _is_dashscope_explicit_image_understanding_model(model_id):
        return False
    return "image" in res_mods or _has_keyword(model_id, DASHSCOPE_IMAGE_GENERATION_KEYWORDS)


def _is_dashscope_video_understanding_model(model_id: str, desc: str, req_mods: set, res_mods: set) -> bool:
    searchable_text = f"{model_id} {desc.lower()}"
    if "video" in req_mods and "text" in res_mods:
        return True
    return _has_keyword(searchable_text, DASHSCOPE_VIDEO_UNDERSTANDING_KEYWORDS)


def _is_dashscope_image_understanding_model(model_id: str, desc: str, req_mods: set, res_mods: set) -> bool:
    searchable_text = f"{model_id} {desc.lower()}"
    if _is_dashscope_image_generation_model(model_id, desc, req_mods, res_mods):
        return False
    if _is_dashscope_video_understanding_model(model_id, desc, req_mods, res_mods):
        return False
    if ("image" in req_mods or "video" in req_mods) and "text" in res_mods:
        return True
    return _is_dashscope_explicit_image_understanding_model(model_id) or _has_keyword(
        searchable_text, DASHSCOPE_IMAGE_UNDERSTANDING_KEYWORDS
    )


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
                    if response.status_code == 429:
                        await asyncio.sleep(2)
                        continue
                    response.raise_for_status()

                    data = response.json()
                    models = data.get("output", {}).get("models", [])

                    # Break loop if no more models on the current page
                    if not models:
                        break

                    all_models.extend(models)
                    if len(models) < 100:
                        break
                    current_page += 1
                    await asyncio.sleep(0.5)

            # Initialize containers for the 6 main categories
            categorized_models = {
                "chat": [],  # Maps to "llm"
                "vlm": [],  # Maps to "vlm"
                "vlm2": [],  # Maps to image generation models
                "vlm3": [],  # Maps to video understanding models
                "embedding": [],  # Maps to "embedding" / "multi_embedding"
                "rerank": [],  # Maps to "rerank"
                "tts": [],  # Maps to "tts"
                "stt": []  # Maps to "stt"
            }

            # Classify models and inject canonical fields expected downstream
            for model_obj in all_models:
                # Extract key fields for logical determination (lowercased for robustness)
                m_id = model_obj.get('model', '').lower()
                desc = model_obj.get('description', '')
                metadata = model_obj.get('inference_metadata') or {}
                req_mod = metadata.get('request_modality', [])
                res_mod = metadata.get('response_modality', [])
                req_mods = _modality_set(req_mod)
                res_mods = _modality_set(res_mod)
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

                # 2. Rerank
                if 'rerank' in m_id.lower() or '重排序' in desc:
                    cleaned_model.update({"model_tag": "rerank", "model_type": "rerank"})
                    categorized_models['rerank'].append(cleaned_model)
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
                if _is_dashscope_video_understanding_model(m_id, desc, req_mods, res_mods):
                    cleaned_model.update({"model_tag": "chat", "model_type": "vlm3"})
                    categorized_models['vlm3'].append(cleaned_model)
                    continue

                if _is_dashscope_image_generation_model(m_id, desc, req_mods, res_mods):
                    cleaned_model.update({"model_tag": "chat", "model_type": "vlm2"})
                    categorized_models['vlm2'].append(cleaned_model)
                    continue

                if _is_dashscope_image_understanding_model(m_id, desc, req_mods, res_mods):
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
                return [
                    {**model, "model_type": target_model_type}
                    for model in categorized_models[target_model_type]
                ]
            else:
                return []
        except (httpx.HTTPStatusError, httpx.ConnectTimeout, httpx.ConnectError, Exception) as e:
            return _classify_provider_error("DashScope", exception=e)

