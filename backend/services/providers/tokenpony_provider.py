import httpx
import ssl

from typing import Dict, List


from consts.const import DEFAULT_LLM_MAX_TOKENS
from consts.provider import TOKENPONY_GET_URL
from services.providers.base import AbstractModelProvider, _classify_provider_error


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
            # response = requests.get(url, headers=headers)
            # all_models=[]
            # if response.status_code == 200:
            #     data = response.json()
            #     # 注意：OpenAI 标准返回是在 "data" 字段下
            #     all_models=data.get("data", [])
            # Fetch all models asynchronously
            async with httpx.AsyncClient(http2=True) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                # OpenAI standard response puts the model list inside the "data" array
                all_models: List[Dict] = response.json().get("data", [])

            # Initialize containers for the 6 main categories
            categorized_models = {
                "chat": [],       # Maps to "llm"
                "vlm": [],        # Maps to "vlm"
                "embedding": [],  # Maps to "embedding" / "multi_embedding"
                "reranker": [],   # Maps to "reranker"
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
                # 1. reranker
                if 'rerank' in m_id:
                    cleaned_model.update({"model_tag": "reranker", "model_type": "reranker"})
                    categorized_models['reranker'].append(cleaned_model)
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

                # 5. VLM (Vision Language Model / Image & Video Generation)

                elif any(keyword in m_id for keyword in ['-vl', 'vl-', 'ocr', 'vision']):
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
                return categorized_models[target_model_type]
            else:
                return []

        except (httpx.HTTPStatusError, httpx.ConnectTimeout, httpx.ConnectError, Exception) as e:
            return _classify_provider_error("TokenPony", exception=e)
