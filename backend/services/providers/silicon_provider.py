import httpx
import logging
from typing import Dict, List

from consts.const import DEFAULT_LLM_MAX_TOKENS
from consts.provider import SILICON_GET_URL
from services.providers.base import AbstractModelProvider, _classify_provider_error, _create_error_response

logger = logging.getLogger("model_provider")


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
            if model_type in ("llm", "vlm", "image_understanding", "video_understanding"):
                silicon_url = f"{SILICON_GET_URL}?sub_type=chat"
            elif model_type in ("embedding", "multi_embedding"):
                silicon_url = f"{SILICON_GET_URL}?sub_type=embedding"
            elif model_type == "rerank":
                silicon_url = f"{SILICON_GET_URL}?sub_type=reranker"
            elif model_type == "image_generation":
                # Image generation uses text-to-image and image-to-image sub_types
                silicon_url = f"{SILICON_GET_URL}?sub_type=text-to-image"
            else:
                silicon_url = SILICON_GET_URL

            logger.info(f"SiliconFlow API request: {silicon_url}")

            async with httpx.AsyncClient(verify=False) as client:
                response = await client.get(silicon_url, headers=headers)
                response.raise_for_status()
                response_data = response.json()

            logger.info(f"SiliconFlow raw API response for {model_type}: {response_data}")

            # Handle cases where data might be None or not present
            model_list: List[Dict] = response_data.get("data") or []
            logger.info(f"SiliconFlow extracted {len(model_list)} models from response")

            # For image_generation, also fetch image-to-image models
            if model_type == "image_generation":
                image_to_image_url = f"{SILICON_GET_URL}?sub_type=image-to-image"
                logger.info(f"Fetching additional image-to-image models: {image_to_image_url}")

                async with httpx.AsyncClient(verify=False) as client:
                    response2 = await client.get(image_to_image_url, headers=headers)
                    response2.raise_for_status()
                    response_data2 = response2.json()

                logger.info(f"SiliconFlow API response for image-to-image: {response_data2}")
                image_to_image_list = response_data2.get("data") or []
                model_list.extend(image_to_image_list)

            # Return empty list if no models found
            if not model_list:
                logger.warning(f"SiliconFlow returned no models for type: {model_type}")
                # Return an error response so the frontend knows the reason
                return _create_error_response(
                    "no_models",
                    f"SiliconFlow API returned empty model list for type '{model_type}'. "
                    f"Please verify that you have models deployed in this category on SiliconFlow."
                )

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
            elif model_type == "rerank":
                for item in model_list:
                    item["model_tag"] = "rerank"
                    item["model_type"] = model_type
            elif model_type in ("image_understanding", "video_understanding"):
                # Image understanding and video understanding use VLM endpoint
                for item in model_list:
                    item["model_tag"] = "vlm"
                    item["model_type"] = model_type
                    item["max_tokens"] = DEFAULT_LLM_MAX_TOKENS
            elif model_type == "image_generation":
                # Filter to only include actual image generation models
                # Use a whitelist of known image generation model patterns
                known_image_gen_patterns = [
                    "flux", "sd-", "stable-diffusion", "dalle", "imagen",
                    "qwen-image", "qwen-image-edit", "z-image", "midjourney",
                    "playground", "pixart", "sdxl", "wurst", "aivinci",
                    "kolors", "wan", "cogview", "emu", "EMU", "FLUX",
                    "SDXL", "DDPM", "diffusion", "image generation",
                    "text-to-image", "image-to-image", "t2i", "i2i"
                ]
                filtered_models = [
                    m for m in model_list
                    if any(pattern in (m.get("id", "") + m.get("name", "")).lower()
                           for pattern in known_image_gen_patterns)
                ]
                logger.info(f"Filtered image generation models: {len(filtered_models)} out of {len(model_list)}")
                if filtered_models:
                    logger.info(f"Filtered models: {[m.get('id', m.get('name', 'unknown')) for m in filtered_models]}")
                else:
                    logger.warning("No image generation models found after filtering. "
                                   f"API returned: {[m.get('id', m.get('name', 'unknown')) for m in model_list]}")
                model_list = filtered_models

                for item in model_list:
                    item["model_tag"] = "image_generation"
                    item["model_type"] = model_type

            logger.info(f"SiliconFlow returning {len(model_list)} models for type {model_type}: {[m.get('id', m.get('name', 'unknown')) for m in model_list]}")
            return model_list
        except (httpx.HTTPStatusError, httpx.ConnectTimeout, httpx.ConnectError, Exception) as e:
            return _classify_provider_error("SiliconFlow", exception=e)
