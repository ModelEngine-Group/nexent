# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""
Analyze Text File Tool

Extracts content from text files (excluding images) and analyzes it using a large language model.
Supports files from S3, HTTP, and HTTPS URLs.
"""

import json
import logging
from typing import List, Optional

from jinja2 import StrictUndefined, Template
from pydantic import Field
from smolagents.tools import Tool

from ...core.utils.observer import MessageObserver
from ...core.utils.tools_common_message import ToolCategory, ToolSign
from ...multi_modal.load_save_object import LoadSaveObjectManager
from ...storage import MinIOStorageClient
from ...storage.errors import DeadlineExceeded, OperationCancelled
from ..prompts import load_prompt


logger = logging.getLogger("analyze_text_file_tool")


class AnalyzeTextFileTool(Tool):
    """Tool for analyzing text file content using a large language model"""

    name = "analyze_text_file"
    description = (
        "Extract content from text files and analyze them using a large language model based on your query. "
        "Supports multiple files from S3 URLs (s3://bucket/key or /bucket/key), HTTP, and HTTPS URLs. "
        "The tool will extract text content from each file and return an analysis based on your question."
    )

    description_zh = "从文本文件中提取内容，并根据你的问题使用大语言模型进行分析。支持来自 S3、HTTP 和 HTTPS URL 的多个文件。支持 s3://bucket/key、/bucket/key、http:// 和 https:// URL。该工具将从每个文件中提取文本内容，并根据你的问题返回分析结果。"

    inputs = {
        "file_url_list": {
            "type": "array",
            "description": "List of file URLs (S3, HTTP, or HTTPS). Supports s3://bucket/key, /bucket/key, http://, and https:// URLs.",
            "description_zh": "文件 URL 列表（S3、HTTP 或 HTTPS）。支持 s3://bucket/key、/bucket/key、http:// 和 https:// URL。",
        },
        "query": {
            "type": "string",
            "description": "User's question to guide the analysis",
            "description_zh": "用户的问题，用于指导分析",
        },
    }

    init_param_descriptions = {
        "storage_client": {"description": "Storage client for downloading files"},
        "text_cleanser": {"description": "Run-bound text cleansing capability provided by the runtime"},
        "llm_model": {"description": "The LLM model to use"},
        "selected_model_id": {
            "description": "Optional Nexent LLM model ID to use for text file analysis. If omitted, the default LLM model is used."
        },
        "validate_url_access": {
            "description": "Callback function to validate URL access permissions (passed to LoadSaveObjectManager)"
        },
    }
    output_type = "array"
    category = ToolCategory.MULTIMODAL.value
    tool_sign = ToolSign.MULTIMODAL_OPERATION.value

    def __init__(
        self,
        storage_client: Optional[MinIOStorageClient] = Field(
            description="Storage client for downloading files from S3 URLs、HTTP URLs、HTTPS URLs.",
            default=None,
            exclude=True,
        ),
        observer: MessageObserver = Field(description="Message observer", default=None, exclude=True),
        text_cleanser: callable = Field(default=None, exclude=True, description="Runtime text cleansing capability"),
        llm_model: str = Field(description="The LLM model to use", default=None, exclude=True),
        selected_model_id: int = Field(
            description="Optional Nexent LLM model ID to use for text file analysis. If omitted, the default LLM model is used.",
            default=None,
        ),
        validate_url_access: callable = Field(
            description="Callback function to validate URL access permissions", default=None, exclude=True
        ),
    ):
        super().__init__()
        self.storage_client = storage_client
        self.observer = observer
        self.llm_model = llm_model
        self.selected_model_id = selected_model_id
        if not callable(text_cleanser):
            raise ValueError("Text cleansing capability is required")
        self.text_cleanser = text_cleanser
        self.cancellation_scope = None

        # Create LoadSaveObjectManager with the storage client and validation callback
        # Ensure validate_url_access is callable before passing to LoadSaveObjectManager
        validate_callback = None
        if validate_url_access is not None and callable(validate_url_access):
            validate_callback = validate_url_access
        self.mm = LoadSaveObjectManager(storage_client=self.storage_client, validate_url_access=validate_callback)
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

        if file_url_list is None:
            raise ValueError("file_url_list cannot be None")

        if not isinstance(file_url_list, list):
            raise ValueError("file_url_list must be a list of bytes")

        try:
            analysis_results: List[str] = []

            for index, single_file in enumerate(file_url_list, start=1):
                logger.info(f"Extracting text content from file #{index}, query: {query}")
                extension = ".json" if self._is_valid_json(single_file) else ".txt"
                filename = f"file_{index}{extension}"

                # Step 1: Get file content
                raw_text = self.text_cleanser(filename, single_file, cancellation_scope=self.cancellation_scope)

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

        except (DeadlineExceeded, OperationCancelled):
            raise
        except Exception as e:
            logger.error(f"Error analyzing text file: {str(e)}", exc_info=True)
            error_msg = f"Error analyzing text file: {str(e)}"
            raise Exception(error_msg)

    @staticmethod
    def _is_valid_json(file_content: bytes) -> bool:
        """Return whether the file content is a valid JSON document."""
        try:
            json.loads(file_content)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            return False
        return True

    def analyze_file(
        self,
        query: str,
        raw_text: str,
    ):
        """
        Process text file, convert to text using external API
        """
        language = getattr(self.observer, "lang", "en") if self.observer else "en"
        prompts = load_prompt(language, "tool/analyze_file")
        system_prompt_template = Template(prompts["system_prompt"], undefined=StrictUndefined)
        user_prompt_template = Template(prompts["user_prompt"], undefined=StrictUndefined)

        system_prompt = system_prompt_template.render({"query": query})
        user_prompt = user_prompt_template.render({})

        result, truncation_percentage = self.llm_model.analyze_long_text(
            text_content=raw_text, system_prompt=system_prompt, user_prompt=user_prompt
        )
        return result.content, truncation_percentage
