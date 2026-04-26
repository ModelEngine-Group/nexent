"""
Analyze Audio Tool

Understand and analyze audio/speech content using a language model.
Supports audio files from S3, HTTP, and HTTPS URLs.
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

logger = logging.getLogger("analyze_audio_tool")


class AnalyzeAudioTool(Tool):
    """Tool for understanding and analyzing audio content using a language model"""

    name = "analyze_audio"
    description = (
        "This tool uses a language model to understand and analyze audio/speech content based on your query and returns a description of the audio.\n"
        "It is used to understand and analyze audio content, with audio sources supporting S3 URLs (s3://bucket/key or /bucket/key), "
        "HTTP, and HTTPS URLs.\n"
        "Use this tool when you want to retrieve information contained in an audio file and provide the audio's URL and your query."
    )

    description_zh = "使用语言模型，根据你的提示词来理解音频内容，并返回音频的描述。可用于理解和分析音频内容，支持 S3 URLs（s3://bucket/key 或 /bucket/key）、HTTP 和 HTTPS URL。"

    inputs = {
        "audio_url": {
            "type": "string",
            "description": "Single audio URL (S3, HTTP, or HTTPS). Supports s3://bucket/key, /bucket/key, http://, and https:// URLs.",
            "description_zh": "音频 URL（S3、HTTP 或 HTTPS）。支持 s3://bucket/key、/bucket/key、http:// 和 https:// URL。",
            "nullable": True
        },
        "audio_urls_list": {
            "type": "array",
            "description": "List of audio URLs (S3, HTTP, or HTTPS). Supports s3://bucket/key, /bucket/key, http://, and https:// URLs.",
            "description_zh": "列表形式输入音频 URL（S3、HTTP 或 HTTPS）。支持 s3://bucket/key、/bucket/key、http:// 和 https:// URL。",
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
            "description": "The language model to use for audio understanding"
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
                description="The language model to use for audio understanding",
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

        self.running_prompt_zh = "正在分析音频..."
        self.running_prompt_en = "Analyzing audio..."

    def forward(self, audio_url: str = None, audio_urls_list: list = None, query: str = None) -> List[str]:
        """
        Forward method that supports both single audio_url and audio_urls_list parameters.
        Downloads audio files from URLs and then processes them.
        """
        from ...multi_modal.load_save_object import UrlType, is_url

        if audio_url is not None:
            audio_urls_list = [audio_url]
        elif audio_urls_list is not None and not isinstance(audio_urls_list, list):
            audio_urls_list = [audio_urls_list]

        if not audio_urls_list:
            raise ValueError("audio_urls_list cannot be empty")

        audio_bytes_list: List[bytes] = []
        for url in audio_urls_list:
            url_type = is_url(url)
            if not url_type:
                raise ValueError(f"Invalid URL: {url}")
            bytes_data = self.mm.download_file_from_url(url, url_type=url_type)
            if bytes_data is None:
                raise ValueError(f"Failed to download audio from URL: {url}")
            audio_bytes_list.append(bytes_data)

        return self._forward_impl(audio_urls_list=audio_bytes_list, query=query)

    def _forward_impl(self, audio_urls_list: List[bytes] = None, query: str = None) -> List[str]:
        """
        Analyze audio files identified by S3 URL, HTTP URL, or HTTPS URL and return the identified content.

        Note: This method receives bytes (already downloaded by the caller).

        Args:
            audio_urls_list: List of audio bytes (already downloaded).
            query: User's question to guide the analysis

        Returns:
            List[str]: One analysis string per audio file that aligns with the order
            of the provided audio files.

        Raises:
            Exception: If the audio cannot be downloaded or analyzed.
        """
        if self.vlm_model is None:
            error_msg_zh = "语言模型未配置，请联系管理员配置模型后重试"
            error_msg_en = "Language model is not configured. Please contact your administrator to configure the model and try again."
            error_msg = error_msg_zh if self._is_chinese else error_msg_en
            logger.error(error_msg)
            raise Exception(error_msg)

        if self.observer:
            running_prompt = self.running_prompt_zh if self._is_chinese else self.running_prompt_en
            self.observer.add_message("", ProcessType.TOOL, running_prompt)

        if audio_urls_list is None:
            raise ValueError("audio_urls cannot be None")

        if not isinstance(audio_urls_list, list):
            raise ValueError("audio_urls must be a list of bytes")

        if not audio_urls_list:
            raise ValueError("audio_urls must contain at least one audio file")

        language = get_observer_lang(self.observer) if self.observer else "en"
        prompts = get_prompt_template(
            template_type='analyze_audio', language=language)
        system_prompt = Template(
            prompts['system_prompt'], undefined=StrictUndefined).render({'query': query})

        try:
            analysis_results: List[str] = []
            for index, audio_bytes in enumerate(audio_urls_list, start=1):
                logger.info(f"Analyzing audio #{index}, query: {query}")
                audio_stream = BytesIO(audio_bytes)
                try:
                    response = self.vlm_model.analyze_audio(
                        audio_input=audio_stream,
                        system_prompt=system_prompt
                    )
                except Exception as e:
                    error_msg_zh = f"音频{index}分析失败: {str(e)}。请检查模型配置是否正确。"
                    error_msg_en = f"Failed to analyze audio #{index}: {str(e)}. Please check if the model is configured correctly."
                    error_msg = error_msg_zh if self._is_chinese else error_msg_en
                    raise Exception(error_msg)

                analysis_results.append(response.content)

            return analysis_results
        except Exception as e:
            logger.error(f"Error analyzing audio: {str(e)}", exc_info=True)
            error_msg = f"Error analyzing audio: {str(e)}"
            raise Exception(error_msg)
