"""
Analyze Text File Tool

Extracts content from text files (excluding images) and analyzes it using a large language model.
Supports files from S3, HTTP, and HTTPS URLs.
"""
import json
import logging
from typing import List, Optional, Union

import httpx
from jinja2 import Template, StrictUndefined
from pydantic import Field
from smolagents.tools import Tool

from nexent.core import MessageObserver
from nexent.core.utils.observer import ProcessType
from nexent.core.utils.prompt_template_utils import get_prompt_template
from nexent.core.utils.tools_common_message import ToolCategory, ToolSign
from nexent.storage import MinIOStorageClient
from nexent.multi_modal.load_save_object import LoadSaveObjectManager


logger = logging.getLogger("analyze_text_file_tool")


class AnalyzeTextFileTool(Tool):
    """Tool for analyzing text file content using a large language model"""

    name = "analyze_text_file"
    description = (
        "Extract content from text files and analyze them using a large language model based on your query. "
        "Supports multiple files from S3 URLs (s3://bucket/key or /bucket/key), HTTP, and HTTPS URLs. "
        "The tool will extract the text content from each file and return an analysis based on your question."
    )

    inputs = {
        "file_url_list": {
            "type": "array",
            "description": "List of file URLs (S3, HTTP, or HTTPS). Supports s3://bucket/key, /bucket/key, http://, and https:// URLs."
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
        storage_client: Optional[MinIOStorageClient] = Field(
            description="Storage client for downloading files from S3 URLs、HTTP URLs、HTTPS URLs.",
            default=None,
            exclude=True
        ),
        observer: MessageObserver = Field(
            description="Message observer",
            default=None,
            exclude=True
        ),
        data_process_service_url: str = Field(
            description="URL of data process service",
            default=None,
            exclude=True),
        llm_model: str = Field(
            description="The LLM model to use",
            default=None,
            exclude=True)
    ):
        super().__init__()
        self.storage_client = storage_client
        self.observer = observer
        self.llm_model = llm_model
        self.data_process_service_url = data_process_service_url
        self.mm = LoadSaveObjectManager(storage_client=self.storage_client)
        self.time_out = 60 * 5

        self.running_prompt_zh = "正在分析文件..."
        self.running_prompt_en = "Analyzing file..."
        # Dynamically apply the load_object decorator to forward method
        self.forward = self.mm.load_object(input_names=["file_url_list"])(self._forward_impl)

    def _forward_impl(
        self,
        file_url_list: List[bytes],
        query: str,
    ) -> List[str]:
        """
        Analyze text file content using a large language model.

        Note: This method is wrapped by load_object decorator which downloads
        the image from S3 URL, HTTP URL, or HTTPS URL and passes bytes to this method.

        Args:
            file_url_list: List of file bytes converted from URLs by the decorator.
                           The load_object decorator converts URLs to bytes before calling this method.
            query: User's question to guide the analysis

        Returns:
            List[str]: One analysis string per file that aligns with the order
        """
        # Send tool run message
        if self.observer:
            running_prompt = self.running_prompt_zh if self.observer.lang == "zh" else self.running_prompt_en
            self.observer.add_message("", ProcessType.TOOL, running_prompt)

        if file_url_list is None:
            raise ValueError("file_url_list cannot be None")

        if not isinstance(file_url_list, list):
            raise ValueError("file_url_list must be a list of bytes")

        try:
            analysis_results: List[str] = []

            for index, single_file in enumerate(file_url_list, start=1):
                logger.info(f"Extracting text content from file #{index}, query: {query}")
                filename = f"file_{index}.txt"

                # Step 1: Get file content
                raw_text = self.process_text_file(filename, single_file)

                if not raw_text:
                    error_msg = f"No text content extracted from file #{index}"
                    logger.error(error_msg)
                    raise Exception(error_msg)

                logger.info(f"Analyzing text content with LLM for file #{index}, query: {query}")

                # Step 2: Analyze file content
                try:
                    text, _ = self.analyze_file(query, raw_text)
                    analysis_results.append(text)
                except Exception as analysis_error:
                    logger.error(f"Failed to analyze file #{index}: {analysis_error}")
                    analysis_results.append(str(analysis_error))

            return analysis_results

        except Exception as e:
            logger.error(f"Error analyzing text file: {str(e)}", exc_info=True)
            error_msg = f"Error analyzing text file: {str(e)}"
            raise Exception(error_msg)


    def process_text_file(self, filename: str, file_content: bytes,) -> str:
        """
        Process text file, convert to text using external API
        """
        # file_content is byte data, need to send to API through file upload
        api_url = f"{self.data_process_service_url}/tasks/process_text_file"
        logger.info(f"Processing text file {filename} with API: {api_url}")

        raw_text = ""
        try:
            # Upload byte data as a file
            files = {
                'file': (filename, file_content, 'application/octet-stream')
            }
            data = {
                'chunking_strategy': 'basic',
                'timeout': self.time_out,
            }
            with httpx.Client(timeout=self.time_out) as client:
                response = client.post(api_url, files=files, data=data)

            if response.status_code == 200:
                result = response.json()
                raw_text = result.get("text", "")
                logger.info(
                    f"File processed successfully: {raw_text[:200]}...{raw_text[-200:]}...， length: {len(raw_text)}")
            else:
                error_detail = response.json().get('detail', 'unknown error') if response.headers.get(
                    'content-type', '').startswith('application/json') else response.text
                logger.error(
                    f"File processing failed (status code: {response.status_code}): {error_detail}")
                raise Exception(error_detail)

        except Exception as e:
            logger.error(f"Failed to process text file {filename}: {str(e)}", exc_info=True)
            raise

        return raw_text

    def analyze_file(self, query: str, raw_text: str,):
        """
        Process text file, convert to text using external API
        """
        language = getattr(self.observer, "lang", "en") if self.observer else "en"
        prompts = get_prompt_template(template_type='analyze_file', language=language)
        system_prompt_template = Template(prompts['system_prompt'], undefined=StrictUndefined)
        user_prompt_template = Template(prompts['user_prompt'], undefined=StrictUndefined)

        system_prompt = system_prompt_template.render({'query': query})
        user_prompt = user_prompt_template.render({})

        result, truncation_percentage = self.llm_model.analyze_long_text(
            text_content=raw_text,
            system_prompt=system_prompt,
            user_prompt=user_prompt
        )
        return result.content, truncation_percentage
