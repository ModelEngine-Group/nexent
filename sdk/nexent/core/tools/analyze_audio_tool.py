"""
Analyze Audio Tool

Analyze audio using the configured video understanding model.
Supports audio from S3, HTTP, and HTTPS URLs.
"""

import logging
from io import BytesIO
from typing import List, Optional

from jinja2 import StrictUndefined, Template
from pydantic import Field
from smolagents.tools import Tool

from ...core.models import OpenAIVLModel
from ...core.utils.observer import MessageObserver, ProcessType
from ...core.utils.prompt_template_utils import get_prompt_template
from ...core.utils.tools_common_message import ToolCategory, ToolSign
from ...multi_modal.load_save_object import LoadSaveObjectManager
from ...multi_modal.utils import detect_content_type_from_bytes
from ...storage import MinIOStorageClient

logger = logging.getLogger("analyze_audio_tool")


class AnalyzeAudioTool(Tool):
    """Tool for understanding and analyzing audio using the video understanding model."""

    name = "analyze_audio"
    skip_forward_signature_validation = True
    description = (
        "This tool uses the configured video understanding model to understand audio based on your query and then returns an audio analysis result.\n"
        "It is used to understand and analyze one audio file, with sources supporting S3 URLs (s3://bucket/key or /bucket/key), "
        "HTTP, and HTTPS URLs.\n"
        "Use this tool when you want to retrieve information contained in audio and provide the audio URL and your query."
    )
    description_zh = (
        "使用视频理解模型，根据你的问题理解音频，并返回音频分析结果。"
        "可用于理解和分析一个音频文件，支持 S3 URL（s3://bucket/key 或 /bucket/key）、HTTP 和 HTTPS URL。"
    )

    inputs = {
        "audio_url": {
            "type": "string",
            "description": "Audio URL (S3, HTTP, or HTTPS). Supports s3://bucket/key, /bucket/key, http://, and https:// URLs.",
            "description_zh": "音频 URL（S3、HTTP 或 HTTPS）。支持 s3://bucket/key、/bucket/key、http:// 和 https:// URL。",
        },
        "query": {
            "type": "string",
            "description": "User's question to guide the audio analysis",
            "description_zh": "用户的问题，用于指导音频分析",
        },
    }

    init_param_descriptions = {
        "observer": {"description": "Message observer"},
        "vlm_model": {"description": "The video understanding model to use"},
        "storage_client": {"description": "Storage client for downloading files"},
        "validate_url_access": {
            "description": "Callback function to validate URL access permissions (passed to LoadSaveObjectManager)"
        },
    }
    output_type = "string"
    category = ToolCategory.MULTIMODAL.value
    tool_sign = ToolSign.MULTIMODAL_OPERATION.value

    def __init__(
            self,
            observer: MessageObserver = Field(
                description="Message observer",
                default=None,
                exclude=True),
            vlm_model: OpenAIVLModel = Field(
                description="The video understanding model to use",
                default=None,
                exclude=True),
            storage_client: MinIOStorageClient = Field(
                description="Storage client for downloading files from S3 URLs, HTTP URLs, and HTTPS URLs.",
                default=None,
                exclude=True),
            validate_url_access: callable = Field(
                description="Callback function to validate URL access permissions",
                default=None,
                exclude=True)
    ):
        super().__init__()
        self.observer = observer
        self.vlm_model = vlm_model
        self.storage_client = storage_client
        self._is_chinese = bool(observer and observer.lang == "zh")

        validate_callback = None
        if validate_url_access is not None and callable(validate_url_access):
            validate_callback = validate_url_access
        self.mm = LoadSaveObjectManager(
            storage_client=self.storage_client,
            validate_url_access=validate_callback,
        )
        self.forward = self.mm.load_object(
            input_names=["audio_url", "audio_urls_list"])(self._forward_impl)

        self.running_prompt_zh = "正在分析音频..."
        self.running_prompt_en = "Analyzing audio..."

    def _validate_audio_capable_model(self) -> None:
        """Fail early for SiliconFlow models that are known not to accept audio input."""
        client_kwargs = getattr(self.vlm_model, "client_kwargs", {}) or {}
        base_url = client_kwargs.get("base_url", "") if isinstance(client_kwargs, dict) else ""
        model_id = str(getattr(self.vlm_model, "model_id", "") or "")

        if "siliconflow" in str(base_url).lower() and model_id and "omni" not in model_id.lower():
            raise ValueError(
                "The selected video understanding model does not support audio input on SiliconFlow. "
                "Please choose a Qwen3-Omni model for analyze_audio."
            )

    def _forward_impl(
            self,
            audio_url: Optional[bytes] = None,
            query: str = "",
            audio_urls_list: Optional[List[bytes]] = None) -> str:
        """Analyze an audio file and return the result as a string."""
        if self.vlm_model is None:
            error_msg_zh = "视频理解模型未配置，请联系管理员配置视频理解模型后重试。"
            error_msg_en = "Video understanding model is not configured. Please contact your administrator to configure the video understanding model and try again."
            error_msg = error_msg_zh if self._is_chinese else error_msg_en
            logger.error(error_msg)
            raise Exception(error_msg)
        self._validate_audio_capable_model()

        if self.observer:
            running_prompt = self.running_prompt_zh if self._is_chinese else self.running_prompt_en
            self.observer.add_message("", ProcessType.TOOL, running_prompt)

        if audio_url is not None:
            audio_items = [audio_url]
        else:
            audio_items = audio_urls_list

        if audio_items is None:
            raise ValueError("audio_url cannot be None")
        if not isinstance(audio_items, list):
            raise ValueError("audio_url must be bytes or audio_urls_list must be a list of bytes")
        if not audio_items:
            raise ValueError("audio_url must contain an audio file")

        language = self.observer.lang if self.observer else "en"
        prompts = get_prompt_template(
            template_type='analyze_audio', language=language)
        system_prompt = Template(
            prompts['system_prompt'], undefined=StrictUndefined).render({'query': query})

        try:
            analysis_results: List[str] = []
            for index, audio_bytes in enumerate(audio_items, start=1):
                logger.info(f"Analyzing audio #{index}, query: {query}")
                content_type = detect_content_type_from_bytes(audio_bytes)
                if not content_type.startswith("audio/"):
                    content_type = "audio/mpeg"
                audio_stream = BytesIO(audio_bytes)
                try:
                    response = self.vlm_model.analyze_audio(
                        audio_input=audio_stream,
                        system_prompt=system_prompt,
                        content_type=content_type,
                    )
                except Exception as e:
                    error_msg_zh = f"音频{index}分析失败: {str(e)}。请检查视频理解模型配置是否正确。"
                    error_msg_en = f"Failed to analyze audio {index}: {str(e)}. Please check if the video understanding model is configured correctly."
                    error_msg = error_msg_zh if self._is_chinese else error_msg_en
                    raise Exception(error_msg)

                analysis_results.append(response.content)

            return "\n\n".join(analysis_results)
        except Exception as e:
            logger.error(f"Error analyzing audio: {str(e)}", exc_info=True)
            raise Exception(f"Error analyzing audio: {str(e)}")
