""""
Analyze Image Tool

Analyze images using a large language model.
Supports images from S3, HTTP, and HTTPS URLs.
"""

import logging
from io import BytesIO
from typing import List

from jinja2 import Template, StrictUndefined
from pydantic import Field
from smolagents.tools import Tool

from ...core.models import OpenAIVLModel
from ...core.utils.observer import MessageObserver, ProcessType
from ...core.utils.prompt_template_utils import get_prompt_template
from ...core.utils.tools_common_message import ToolCategory, ToolSign
from ...storage import MinIOStorageClient
from ...multi_modal.load_save_object import LoadSaveObjectManager

logger = logging.getLogger("analyze_image_tool")


class AnalyzeImageTool(Tool):
    """Tool for understanding and analyzing image using a visual language model"""

    name = "analyze_image"
    description = (
        "This tool uses a visual language model to understand images based on your query and then returns a description of the image.\n"
        "It is used to understand and analyze multiple images, with image sources supporting S3 URLs (s3://bucket/key or /bucket/key), "
        "HTTP, and HTTPS URLs.\n"
        "Use this tool when you want to retrieve information contained in an image and provide the image's URL and your query."
    )
    inputs = {
        "image_urls_list": {
            "type": "array",
            "description": "List of image URLs (S3, HTTP, or HTTPS). Supports s3://bucket/key, /bucket/key, http://, and https:// URLs.",
        },
        "query": {
            "type": "string",
            "description": "User's question to guide the analysis"
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
        # Create LoadSaveObjectManager with the storage client
        self.mm = LoadSaveObjectManager(storage_client=self.storage_client)

        # Dynamically apply the load_object decorator to forward method
        self.forward = self.mm.load_object(input_names=["image_urls_list"])(self._forward_impl)

        self.running_prompt_zh = "正在分析图片..."
        self.running_prompt_en = "Analyzing image..."

    def _forward_impl(self, image_urls_list: List[bytes], query: str) -> List[str]:
        """
        Analyze images identified by S3 URL, HTTP URL, or HTTPS URL and return the identified text.

        Note: This method is wrapped by load_object decorator which downloads
        the image from S3 URL, HTTP URL, or HTTPS URL and passes bytes to this method.

        Args:
            image_urls_list: List of image bytes converted from URLs by the decorator.
                             The load_object decorator converts URLs to bytes before calling this method.
            query: User's question to guide the analysis

        Returns:
            List[str]: One analysis string per image that aligns with the order
            of the provided images.

        Raises:
            Exception: If the image cannot be downloaded or analyzed.
        """
        # Send tool run message
        if self.observer:
            running_prompt = self.running_prompt_zh if self.observer.lang == "zh" else self.running_prompt_en
            self.observer.add_message("", ProcessType.TOOL, running_prompt)

        if image_urls_list is None:
            raise ValueError("image_urls cannot be None")

        if not isinstance(image_urls_list, list):
            raise ValueError("image_urls must be a list of bytes")

        if not image_urls_list:
            raise ValueError("image_urls must contain at least one image")

        # Load prompts from yaml file
        language = self.observer.lang if self.observer else "en"
        prompts = get_prompt_template(template_type='analyze_image', language=language)
        system_prompt = Template(prompts['system_prompt'], undefined=StrictUndefined).render({'query': query})

        try:
            analysis_results: List[str] = []
            for index, image_bytes in enumerate(image_urls_list, start=1):
                logger.info(f"Extracting image #{index}, query: {query}")
                image_stream = BytesIO(image_bytes)
                try:
                    response = self.vlm_model.analyze_image(
                        image_input=image_stream,
                        system_prompt=system_prompt
                    )
                except Exception as e:
                    raise Exception(f"Error understanding image {index}: {str(e)}")

                analysis_results.append(response.content)

            return analysis_results
        except Exception as e:
            logger.error(f"Error analyzing image: {str(e)}", exc_info=True)
            error_msg = f"Error analyzing image: {str(e)}"
            raise Exception(error_msg)
