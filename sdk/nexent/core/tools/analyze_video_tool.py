"""
Analyze Video Tool

Understand and analyze video content using a vision language model.
Supports videos from S3, HTTP, and HTTPS URLs.
"""

import logging
from io import BytesIO
from typing import List

from jinja2 import Template, StrictUndefined
from pydantic import Field
from smolagents.tools import Tool

from ...core.models import OpenAIVLModel
from ...core.utils.observer import MessageObserver, ProcessType, get_observer_lang
from ...core.utils.prompt_template_utils import get_prompt_template
from ...core.utils.tools_common_message import ToolCategory, ToolSign
from ...storage import MinIOStorageClient
from ...multi_modal.load_save_object import LoadSaveObjectManager

logger = logging.getLogger("analyze_video_tool")


class AnalyzeVideoTool(Tool):
    """Tool for understanding and analyzing video content using a vision language model"""

    name = "analyze_video"
    description = (
        "This tool uses a vision language model to understand and analyze video content based on your query and returns a description of the video.\n"
        "It is used to understand and analyze video content, with video sources supporting S3 URLs (s3://bucket/key or /bucket/key), "
        "HTTP, and HTTPS URLs.\n"
        "IMPORTANT: When calling this tool, you must pass a LIST of video URLs to the 'video_urls_list' parameter (even for a single video, wrap it in a list), "
        "and pass your question to the 'query' parameter.\n"
        "Example call: analyze_video(video_urls_list=['s3://bucket/video.mp4'], query='Describe this video')"
    )

    description_zh = (
        "使用视觉语言模型，根据你的提示词来理解视频内容，并返回视频的描述。可用于理解和分析视频内容，支持 S3 URLs（s3://bucket/key 或 /bucket/key）、HTTP 和 HTTPS URL。\n"
        "重要：调用此工具时，必须将视频URL列表传递给 'video_urls_list' 参数（即使只有一个视频也要用列表格式），将问题传递给 'query' 参数。\n"
        "示例调用：analyze_video(video_urls_list=['s3://bucket/video.mp4'], query='描述这个视频')"
    )

    inputs = {
        "video_url": {
            "type": "string",
            "description": "Single video URL (S3, HTTP, or HTTPS). Supports s3://bucket/key, /bucket/key, http://, and https:// URLs.",
            "description_zh": "视频 URL（S3、HTTP 或 HTTPS）。支持 s3://bucket/key、/bucket/key、http:// 和 https:// URL。",
            "nullable": True
        },
        "video_urls_list": {
            "type": "array",
            "description": "List of video URLs (S3, HTTP, or HTTPS). Supports s3://bucket/key, /bucket/key, http://, and https:// URLs.",
            "description_zh": "列表形式输入视频 URL（S3、HTTP 或 HTTPS）。支持 s3://bucket/key、/bucket/key、http:// 和 https:// URL。",
            "nullable": True
        },
        "query": {
            "type": "string",
            "description": "User's question to guide the analysis",
            "description_zh": "用户的问题，用于指导分析",
            "nullable": True
        }
    }

    init_param_descriptions = {
        "observer": {
            "description": "Message observer"
        },
        "vlm_model": {
            "description": "The VLM model to use"
        },
        "storage_client": {
            "description": "Storage client for downloading files"
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
                description="The VLM model to use",
                default=None,
                exclude=True),
            storage_client: MinIOStorageClient = Field(
                description="Storage client for downloading files from S3 URLs、HTTP URLs、HTTPS URLs.",
                default=None,
                exclude=True)
    ):
        super().__init__()
        self.observer = observer
        self.vlm_model = vlm_model
        self.storage_client = storage_client

        self._is_chinese = bool(observer and get_observer_lang(observer) == "zh")

        self.mm = LoadSaveObjectManager(storage_client=self.storage_client)

        self.running_prompt_zh = "正在分析视频..."
        self.running_prompt_en = "Analyzing video..."

    def forward(self, video_url: str = None, video_urls_list: list = None, query: str = None) -> List[str]:
        """
        Forward method that supports both single video_url and video_urls_list parameters.
        Downloads video files from URLs and then processes them.
        """
        from ...multi_modal.load_save_object import UrlType, is_url

        if video_url is not None:
            video_urls_list = [video_url]
        elif video_urls_list is not None and not isinstance(video_urls_list, list):
            video_urls_list = [video_urls_list]

        if not video_urls_list:
            raise ValueError("video_urls_list cannot be empty")

        video_bytes_list: List[bytes] = []
        for url in video_urls_list:
            url_type = is_url(url)
            if not url_type:
                raise ValueError(f"Invalid URL: {url}")
            bytes_data = self.mm.download_file_from_url(url, url_type=url_type)
            if bytes_data is None:
                raise ValueError(f"Failed to download video from URL: {url}")
            video_bytes_list.append(bytes_data)

        return self._forward_impl(video_urls_list=video_bytes_list, query=query)

    def _forward_impl(self, video_urls_list: List[bytes] = None, query: str = None) -> List[str]:
        """
        Analyze videos identified by S3 URL, HTTP URL, or HTTPS URL and return the identified content.

        Note: This method is wrapped by load_object decorator which downloads
        the video from S3 URL, HTTP URL, or HTTPS URL and passes bytes to this method.

        Args:
            video_urls_list: List of video bytes converted from URLs by the decorator.
                            The load_object decorator converts URLs to bytes before calling this method.
            query: User's question to guide the analysis

        Returns:
            List[str]: One analysis string per video that aligns with the order
            of the provided videos.

        Raises:
            Exception: If the video cannot be downloaded or analyzed.
        """
        if self.vlm_model is None:
            error_msg_zh = "视觉语言模型(VLM)未配置，请联系管理员配置VLM模型后重试"
            error_msg_en = "Vision Language Model (VLM) is not configured. Please contact your administrator to configure the VLM model and try again."
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

        language = get_observer_lang(self.observer) if self.observer else "en"
        prompts = get_prompt_template(
            template_type='analyze_video', language=language)
        system_prompt = Template(
            prompts['system_prompt'], undefined=StrictUndefined).render({'query': query})

        try:
            analysis_results: List[str] = []
            for index, video_bytes in enumerate(video_urls_list, start=1):
                logger.info(f"Analyzing video #{index}, query: {query}")
                video_stream = BytesIO(video_bytes)
                try:
                    response = self.vlm_model.analyze_video(
                        video_input=video_stream,
                        system_prompt=system_prompt
                    )
                except Exception as e:
                    error_msg_zh = f"视频{index}分析失败: {str(e)}。请检查VLM模型配置是否正确。"
                    error_msg_en = f"Failed to analyze video {index}: {str(e)}. Please check if the VLM model is configured correctly."
                    error_msg = error_msg_zh if self._is_chinese else error_msg_en
                    raise Exception(error_msg)

                analysis_results.append(response.content)

            return analysis_results
        except Exception as e:
            logger.error(f"Error analyzing video: {str(e)}", exc_info=True)
            error_msg = f"Error analyzing video: {str(e)}"
            raise Exception(error_msg)
