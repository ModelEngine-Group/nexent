import logging
import httpx
from typing import Dict, List

from consts.const import DEFAULT_LLM_MAX_TOKENS
from consts.provider import (
    SILICON_GET_URL,
    SILICON_BASE_URL,
)
from services.providers.base import AbstractModelProvider, _classify_provider_error

logger = logging.getLogger("silicon_provider")

# Silicon Flow image generation endpoint
SILICON_IMAGE_GEN_URL = "https://api.siliconflow.cn/v1/images/generations"


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
            # Normalize model_type to snake_case for consistency
            # Convert camelCase to snake_case (e.g., "imageUnderstanding" -> "image_understanding")
            import re
            model_type_normalized = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', model_type).lower()
            model_api_key: str = provider_config["api_key"]

            headers = {"Authorization": f"Bearer {model_api_key}"}

            # Build URL with type and tag parameters
            silicon_url = SILICON_GET_URL
            params = []

            # Choose sub_type by model type
            if model_type_normalized in ("llm", "vlm", "image_understanding", "image_generation", "video_understanding"):
                params.append("sub_type=chat")
            elif model_type_normalized in ("embedding", "multi_embedding"):
                params.append("sub_type=embedding")
            elif model_type_normalized == "rerank":
                params.append("sub_type=reranker")

            # Note: SiliconFlow API does NOT support 'tag' parameter
            # We only use sub_type for filtering, then filter by model ID keywords after getting results

            if params:
                silicon_url = f"{silicon_url}?{'&'.join(params)}"

            async with httpx.AsyncClient(verify=False) as client:
                response = await client.get(silicon_url, headers=headers)
                response.raise_for_status()
                model_list: List[Dict] = response.json()["data"]

            # Log the API response for debugging
            logger.info(f"SiliconFlow API response: type={model_type}, url={silicon_url}, raw_count={len(model_list)}")
            logger.info(f"SiliconFlow raw model IDs: {[m.get('id') for m in model_list[:20]]}")  # Log first 20

            # Annotate models with canonical fields expected downstream
            if model_type_normalized in ("llm", "vlm", "image_understanding", "image_generation", "video_understanding"):
                for item in model_list:
                    item["model_tag"] = "chat"
                    item["model_type"] = model_type_normalized
                    item["max_tokens"] = DEFAULT_LLM_MAX_TOKENS

                # For LLM, exclude models with vision/video/image generation keywords
                # (in case API tag filter is not precise enough)
                if model_type_normalized == "llm":
                    llm_exclude_keywords = [
                        "-vl", "vl-", "vision", "video",
                        "image_gen", "img_gen", "wanx", "flux",
                        "stable-diffusion", "dall", "llava",
                        "qwen-v", "qwen2-v", "qwen2.5-v", "qvq",
                        "internvl", "intern-vl", "minicpm-v",
                        "glm-4v", "gpt-4v", "gpt-4o",
                        "claude-3-opus", "claude-3-sonnet",
                        "gemini",
                    ]
                    model_list = [
                        m for m in model_list
                        if not any(kw in m.get("id", "").lower() for kw in llm_exclude_keywords)
                    ]
                    logger.info(f"SiliconFlow LLM models after filter: {[m.get('id') for m in model_list]}")

                # For image_understanding (VLM), filter by VLM-related keywords in model ID
                # SiliconFlow API doesn't support tag filter, so we filter after getting results
                elif model_type_normalized == "image_understanding":
                    # More comprehensive VLM keywords to catch all vision models
                    vlm_keywords = [
                        # Vision/VLM keywords
                        "vl", "-vl", "vision", "vlm",
                        "qwen-v", "qwen2-v", "qwen2.5-v", "qwen2-5-v", "qvq", "qwen-vl",
                        "qwen-vl-", "qwen2.5-vl-", "qwen2.5vl-", "qwen2-vl-",  # Qwen VL series with size
                        "qwen3-vl", "qwen3-vl-",  # Qwen3 VL series
                        "internvl", "intern-vl", "minicpm-v",
                        "glm-4v", "glm-4v-plus", "glm-4v-max", "glm-4v-flash",
                        "gpt-4v", "gpt-4o", "gpt-4-turbo",
                        "claude-3", "claude-3.5",
                        "gemini",
                        # Moonshot/Kimi
                        "moonshot", "kimi", "kimi-vl",
                        # Llava
                        "llava",
                        # Video understanding (can also process images)
                        "video", "videovision", "video-chat",
                        # OCR models
                        "ocr", "deepseek-ocr", "paddleocr", "paddleocr-vl",
                        # Other vision models
                        "ring-flash",
                        # Cog
                        "cog", "cogvlm", "cogagent",
                        # Other multimodal
                        "qwen-vl", "qwen2.5-vl", "qwen2.5vl",
                        "step-1", "step1v",
                        "emu", "emovla",
                        # Keep these shorter patterns at the end
                        "vl-", "-vl", "vision",
                    ]
                    original_count = len(model_list)
                    model_list = [
                        m for m in model_list
                        if any(kw in m.get("id", "").lower() for kw in vlm_keywords)
                    ]
                    logger.info(f"SiliconFlow VLM: raw={original_count}, filtered={len(model_list)}")
                    logger.info(f"SiliconFlow VLM models after filter: {[m.get('id') for m in model_list]}")

                # For video understanding, filter by video-related keywords
                elif model_type_normalized == "video_understanding":
                    video_keywords = [
                        "video", "videovision", "video-chat",
                        "qvq", "qwen-vl", "qwen2-v",
                    ]
                    model_list = [
                        m for m in model_list
                        if any(kw in m.get("id", "").lower() for kw in video_keywords)
                    ]
                    logger.info(f"SiliconFlow video models after filter: {[m.get('id') for m in model_list]}")

                # For image generation, filter by image generation keywords
                # (API may not have a specific tag for image generation)
                elif model_type_normalized == "image_generation":
                    model_list = [
                        m for m in model_list
                        if any(kw in m.get("id", "").lower() for kw in [
                            "image_gen", "img_gen", "wanx", "flux",
                            "stable-diffusion", "dall", "sd-", "sdxl",
                            "midjourney", "imgen", "t2i", "text2img",
                            "qwen-img", "qwen-image", "cog", "minimax",
                            "polux", "edit", "image-edit"
                        ])
                    ]
                    logger.info(f"SiliconFlow image generation models after filter: {[m.get('id') for m in model_list]}")
            elif model_type_normalized in ("embedding", "multi_embedding"):
                for item in model_list:
                    item["model_tag"] = "embedding"
                    item["model_type"] = model_type
            elif model_type_normalized == "rerank":
                for item in model_list:
                    item["model_tag"] = "rerank"
                    item["model_type"] = model_type

            # For image generation models, set the correct base_url
            if model_type_normalized == "image_generation":
                for item in model_list:
                    # Set the image generation endpoint as base_url
                    item["base_url"] = SILICON_IMAGE_GEN_URL

            # Return empty list to indicate successful API call but no models
            if not model_list:
                return []

            return model_list
        except (httpx.HTTPStatusError, httpx.ConnectTimeout, httpx.ConnectError, Exception) as e:
            return _classify_provider_error("SiliconFlow", exception=e)
