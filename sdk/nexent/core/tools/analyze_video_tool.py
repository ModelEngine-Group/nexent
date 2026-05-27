"""
Analyze Video Tool

Analyze videos using the configured video understanding model.
Supports videos from S3, HTTP, and HTTPS URLs.
"""

import logging
from io import BytesIO
from typing import List

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

logger = logging.getLogger("analyze_video_tool")


class AnalyzeVideoTool(Tool):
    """Tool for understanding and analyzing videos using the video understanding model."""

    name = "analyze_video"
    description = (
        "This tool uses the configured video understanding model to understand videos based on your query and then returns a video analysis result.\n"
        "It is used to understand and analyze multiple videos, with sources supporting S3 URLs (s3://bucket/key or /bucket/key), "
        "HTTP, and HTTPS URLs.\n"
        "Use this tool when you want to retrieve information contained in a video and provide the video's URL and your query."
    )
    description_zh = (
        "使用视频理解模型，根据你的提示词来理解视频，并返回视频分析结果。"
        "可用于理解和分析多个视频，支持 S3 URLs（s3://bucket/key 或 /bucket/key）、HTTP 和 HTTPS URL。"
    )

    inputs = {
        "video_urls_list": {
            "type": "array",
            "description": "List of video URLs (S3, HTTP, or HTTPS). Supports s3://bucket/key, /bucket/key, http://, and https:// URLs.",
            "description_zh": "列表形式输入视频 URL（S3、HTTP 或 HTTPS）。支持 s3://bucket/key、/bucket/key、http:// 和 https:// URL。"
        },
        "query": {
            "type": "string",
            "description": "User's question to guide the video analysis",
            "description_zh": "用户用于指导视频分析的问题"
        }
    }

    init_param_descriptions = {
        "observer": {"description": "Message observer"},
        "vlm_model": {"description": "The video understanding model to use"},
        "storage_client": {"description": "Storage client for downloading files"},
        "validate_url_access": {
            "description": "Callback function to validate URL access permissions (passed to LoadSaveObjectManager)"
        }
    }
    output_type = "array"
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
            validate_url_access=validate_callback
        )
        self.forward = self.mm.load_object(
            input_names=["video_urls_list"])(self._forward_impl)

        self.running_prompt_zh = "正在分析视频..."
        self.running_prompt_en = "Analyzing video..."

    def _forward_impl(self, video_urls_list: List[bytes], query: str) -> List[str]:
        """Analyze videos and return one result per video input."""
        if self.vlm_model is None:
            error_msg_zh = "视频理解模型未配置，请联系管理员配置视频理解模型后重试"
            error_msg_en = "Video understanding model is not configured. Please contact your administrator to configure the video understanding model and try again."
            error_msg = error_msg_zh if self._is_chinese else error_msg_en
            logger.error(error_msg)
            raise Exception(error_msg)

        if self.observer:
            running_prompt = self.running_prompt_zh if self._is_chinese else self.running_prompt_en
            self.observer.add_message("", ProcessType.TOOL, running_prompt)

        if video_urls_list is None:
            raise ValueError("video_urls cannot be None")
        if not isinstance(video_urls_list, list):
            raise ValueError("video_urls must be a list of bytes")
        if not video_urls_list:
            raise ValueError("video_urls must contain at least one video")

        language = self.observer.lang if self.observer else "en"
        prompts = get_prompt_template(
            template_type='analyze_video', language=language)
        system_prompt = Template(
            prompts['system_prompt'], undefined=StrictUndefined).render({'query': query})

        try:
            analysis_results: List[str] = []
            for index, video_bytes in enumerate(video_urls_list, start=1):
                logger.info(f"Analyzing video #{index}, query: {query}")
                content_type = detect_content_type_from_bytes(video_bytes)
                if not content_type.startswith("video/"):
                    content_type = "video/mp4"
                video_stream = BytesIO(video_bytes)
                try:
                    response = self.vlm_model.analyze_video(
                        video_input=video_stream,
                        system_prompt=system_prompt,
                        content_type=content_type
                    )
                except Exception as e:
                    error_msg_zh = f"视频{index}分析失败: {str(e)}。请检查视频理解模型配置是否正确。"
                    error_msg_en = f"Failed to analyze video {index}: {str(e)}. Please check if the video understanding model is configured correctly."
                    error_msg = error_msg_zh if self._is_chinese else error_msg_en
                    raise Exception(error_msg)

                analysis_results.append(response.content)

            return analysis_results
        except Exception as e:
            logger.error(f"Error analyzing video: {str(e)}", exc_info=True)
            raise Exception(f"Error analyzing video: {str(e)}")
