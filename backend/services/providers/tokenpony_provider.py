import httpx
import ssl

from typing import Dict, List


from consts.const import DEFAULT_LLM_MAX_TOKENS
from consts.provider import TOKENPONY_GET_URL
from services.providers.base import AbstractModelProvider, _classify_provider_error


TOKENPONY_IMAGE_UNDERSTANDING_KEYWORDS = (
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
    "gpt-4o",
    "qwen3.6",
    "qwen-3.6",
)
TOKENPONY_IMAGE_GENERATION_KEYWORDS = (
    "image",
    "dall",
    "flux",
    "stable-diffusion",
    "sdxl",
    "midjourney",
    "wanx",
    "kolors",
    "seedream",
    "ideogram",
    "recraft",
)
TOKENPONY_VIDEO_UNDERSTANDING_KEYWORDS = ("omni", "video")


def _has_keyword(text: str, keywords: tuple) -> bool:
    return any(keyword in text for keyword in keywords)


def _is_tokenpony_explicit_image_understanding_model(model_id: str) -> bool:
    return _has_keyword(model_id, TOKENPONY_IMAGE_UNDERSTANDING_KEYWORDS)


def _is_tokenpony_image_generation_model(model_id: str) -> bool:
    if _is_tokenpony_explicit_image_understanding_model(model_id):
        return False
    return _has_keyword(model_id, TOKENPONY_IMAGE_GENERATION_KEYWORDS)


def _is_tokenpony_video_understanding_model(model_id: str) -> bool:
    return _has_keyword(model_id, TOKENPONY_VIDEO_UNDERSTANDING_KEYWORDS)


def _is_tokenpony_image_understanding_model(model_id: str) -> bool:
    if _is_tokenpony_image_generation_model(model_id):
        return False
    if _is_tokenpony_video_understanding_model(model_id):
        return False
    return _is_tokenpony_explicit_image_understanding_model(model_id)


class TokenPonyModelProvider(AbstractModelProvider):
    """Concrete implementation for TokenPony provider."""

    async def get_models(self, provider_config: Dict) -> List[Dict]:
        """
        Fetch models from TokenPony API, categorize them based on modality/ID,
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
            url = TOKENPONY_GET_URL


            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            ssl_context.set_ciphers("DEFAULT@SECLEVEL=1")

            async with httpx.AsyncClient(http2=True) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                # OpenAI standard response puts the model list inside the "data" array
                all_models: List[Dict] = response.json().get("data", [])

            # Initialize containers for the 6 main categories
            categorized_models = {
                "chat": [],       # Maps to "llm"
                "vlm": [],        # Maps to "vlm"
                "vlm2": [],       # Maps to image generation models
                "vlm3": [],       # Maps to video understanding models
                "embedding": [],  # Maps to "embedding" / "multi_embedding"
                "rerank": [],   # Maps to "rerank"
                "tts": [],        # Maps to "tts"
                "stt": []         # Maps to "stt"
            }

            # Classify models and inject canonical fields expected downstream
            for model_obj in all_models:
                m_id = model_obj['id'].lower()
                model_obj.setdefault("object", model_obj.get("object", "model"))
                model_obj.setdefault("owned_by", model_obj.get("owned_by", "tokenpony"))
                cleaned_model = {
                    "id": m_id,
                    "object": model_obj.get("object"),
                    "created": 0,
                    "owned_by": model_obj.get("owned_by"),
                    "model_tag": "",
                    "model_type": "",
                    "max_tokens": DEFAULT_LLM_MAX_TOKENS
                }
                # 1. rerank
                if 'rerank' in m_id:
                    cleaned_model.update({"model_tag": "rerank", "model_type": "rerank"})
                    categorized_models['rerank'].append(cleaned_model)
                #2. embedding
                elif 'embedding' in m_id or m_id.startswith('bge-'):
                    cleaned_model.update({"model_tag": "embedding", "model_type": "embedding"})
                    categorized_models['embedding'].append(cleaned_model)

                # 3. STT (Speech-to-Text / Audio understanding)
                elif 'stt' in m_id:
                    cleaned_model.update({"model_tag": "stt", "model_type": "stt"})
                    categorized_models['stt'].append(cleaned_model)


                # 4. TTS (Text-to-Speech)
                elif 'tts' in m_id:
                    cleaned_model.update({"model_tag": "tts", "model_type": "tts"})
                    categorized_models['tts'].append(cleaned_model)

                # 5. Multimodal models
                elif _is_tokenpony_video_understanding_model(m_id):
                    cleaned_model.update({"model_tag": "chat", "model_type": "vlm3"})
                    categorized_models['vlm3'].append(cleaned_model)
                elif _is_tokenpony_image_generation_model(m_id):
                    cleaned_model.update({"model_tag": "chat", "model_type": "vlm2"})
                    categorized_models['vlm2'].append(cleaned_model)
                elif _is_tokenpony_image_understanding_model(m_id):
                    cleaned_model.update({"model_tag": "chat", "model_type": "vlm"})
                    categorized_models['vlm'].append(cleaned_model)

                # 6. Chat (Pure Text Conversation / Reasoning)
                # Fallback check added: 'not metadata' catches standard OpenAI models that lack modality data
                else :
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
            return _classify_provider_error("TokenPony", exception=e)
