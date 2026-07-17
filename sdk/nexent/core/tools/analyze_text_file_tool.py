"""
Analyze Text File Tool

Extracts content from text files (excluding images) and analyzes it using a large language model.
Supports files from S3, HTTP, and HTTPS URLs.
"""
import json
import logging
from typing import List, Optional

from jinja2 import Template, StrictUndefined
from pydantic import Field
import zipfile
import io
import olefile
from smolagents.tools import Tool

from ...core.utils.observer import MessageObserver, ProcessType
from ...core.utils.prompt_template_utils import get_prompt_template
from ...core.utils.tools_common_message import ToolCategory, ToolSign, SearchResultTextMessage
from ...storage import MinIOStorageClient
from ...multi_modal.load_save_object import LoadSaveObjectManager
from ...utils.http_client_manager import http_client_manager


logger = logging.getLogger("analyze_text_file_tool")


class AnalyzeTextFileTool(Tool):
    """Tool for analyzing text file content using a large language model"""

    name = "analyze_text_file"
    description = (
        "Extract content from text files and analyze them using a large language model based on your query. "
        "Supports multiple files from S3 URLs (s3://bucket/key or /bucket/key), HTTP, and HTTPS URLs. "
        "The tool will extract text content from each file and return an analysis based on your question."
    )

    description_zh = "从文件中提取内容，并根据你的问题使用大语言模型进行分析。支持来自 S3、HTTP 和 HTTPS URL 的多个文件。支持 s3://bucket/key、/bucket/key、http:// 和 https:// URL。该工具将从每个文件中提取文本内容以及图片元数据，并根据你的问题返回分析结果。"

    inputs = {
        "file_url_list": {
            "type": "array",
            "description": "List of file URLs (S3, HTTP, or HTTPS). Supports s3://bucket/key, /bucket/key, http://, and https:// URLs.",
            "description_zh": "文件 URL 列表（S3、HTTP 或 HTTPS）。支持 s3://bucket/key、/bucket/key、http:// 和 https:// URL。"
        },
        "query": {
            "type": "string",
            "description": "User's question to guide the analysis",
            "description_zh": "用户的问题，用于指导分析"
        }
    }

    init_param_descriptions = {
        "storage_client": {
            "description": "Storage client for downloading files"
        },
        "data_process_service_url": {
            "description": "URL of data process service"
        },
        "llm_model": {
            "description": "The LLM model to use"
        },
        "selected_model_id": {
            "description": "Optional Nexent LLM model ID to use for text file analysis. If omitted, the default LLM model is used."
        },
        "validate_url_access": {
            "description": "Callback function to validate URL access permissions (passed to LoadSaveObjectManager)"
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
            exclude=True),
        selected_model_id: int = Field(
            description="Optional Nexent LLM model ID to use for text file analysis. If omitted, the default LLM model is used.",
            default=None),
        validate_url_access: callable = Field(
            description="Callback function to validate URL access permissions",
            default=None,
            exclude=True)
    ):
        super().__init__()
        self.storage_client = storage_client
        self.observer = observer
        self.llm_model = llm_model
        self.selected_model_id = selected_model_id
        self.data_process_service_url = data_process_service_url

        # Create LoadSaveObjectManager with the storage client and validation callback
        # Ensure validate_url_access is callable before passing to LoadSaveObjectManager
        validate_callback = None
        if validate_url_access is not None and callable(validate_url_access):
            validate_callback = validate_url_access
        self.mm = LoadSaveObjectManager(
            storage_client=self.storage_client,
            validate_url_access=validate_callback
        )
        self.time_out = 60 * 5
        self.record_ops = 1

        self.running_prompt_zh = "正在分析文件..."
        self.running_prompt_en = "Analyzing file..."
        # Dynamically apply the load_object decorator to forward method
        self.forward = self.mm.load_object(
            input_names=["file_url_list"])(self._forward_impl)

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
                # add type check
                if not isinstance(single_file, bytes):
                    logger.error(
                        f"Expected 'bytes' for file #{index}, but got {type(single_file).__name__}. "
                        f"Please check the file_url_list."
                    )
                    continue
                
                logger.info(
                    f"Extracting text content and image info from file #{index}, query: {query}")
                
                # detect file type
                file_extension = self.detect_file_type(single_file)
                
                filename = f"file_{index}.{file_extension}"

                # Step 1: Get file content
                raw_text = self.process_text_file(filename, single_file)

                if not raw_text:
                    error_msg = f"No text content extracted from file #{index}"
                    logger.error(error_msg)
                    raise Exception(error_msg)

                logger.info(
                    f"Analyzing text content with LLM for file #{index}, query: {query}")

                # Step 2: Analyze file content
                try:
                    text, _ = self.analyze_file(query, raw_text)
                    analysis_results.append(text)
                except Exception as analysis_error:
                    logger.error(
                        f"Failed to analyze file #{index}: {analysis_error}")
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
            # Use shared HttpClientManager for connection pooling
            client = http_client_manager.get_sync_client(
                base_url=self.data_process_service_url,
                timeout=float(self.time_out),
                verify_ssl=True
            )
            response = client.post(api_url, files=files, data=data)

            if response.status_code == 200:
                result = response.json()
                
                # process image information
                images_list_url, image_info = result.get("images_info", ([], []))
                if images_list_url:
                    search_images_list_json = json.dumps(
                        {"images_url": images_list_url}, ensure_ascii=False
                    )
                    self.observer.add_message(
                        "", ProcessType.PICTURE_WEB, search_images_list_json
                    )
                if image_info:
                    search_results_json = self._build_search_results(image_info)
                    self.record_ops += len(image_info)
                    search_results_data = json.dumps(search_results_json, ensure_ascii=False)
                    self.observer.add_message("", ProcessType.SEARCH_CONTENT, search_results_data)
                
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
            logger.error(
                f"Failed to process text file {filename}: {str(e)}", exc_info=True)
            raise

        return raw_text

    def analyze_file(self, query: str, raw_text: str,):
        """
        Process text file, convert to text using external API
        """
        language = getattr(self.observer, "lang",
                           "en") if self.observer else "en"
        prompts = get_prompt_template(
            template_type='analyze_file', language=language)
        system_prompt_template = Template(
            prompts['system_prompt'], undefined=StrictUndefined)
        user_prompt_template = Template(
            prompts['user_prompt'], undefined=StrictUndefined)

        system_prompt = system_prompt_template.render({'query': query})
        user_prompt = user_prompt_template.render({})

        result, truncation_percentage = self.llm_model.analyze_long_text(
            text_content=raw_text,
            system_prompt=system_prompt,
            user_prompt=user_prompt
        )
        return result.content, truncation_percentage

    def detect_file_type(self, file_bytes: bytes) -> str:
        if file_bytes.startswith(b"%PDF"):
            return "pdf"

        try:
            # doc/xls/ppt
            if file_bytes.startswith(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"):
                ole = olefile.OleFileIO(io.BytesIO(file_bytes))

                for stream, file_type in {
                    "WordDocument": "doc",
                    "Workbook": "xls",
                    "Book": "xls",
                    "PowerPoint Document": "ppt",
                }.items():
                    if ole.exists(stream):
                        return file_type

            # docx/xlsx/pptx
            elif file_bytes.startswith(b"PK"):
                names = set(zipfile.ZipFile(io.BytesIO(file_bytes)).namelist())

                for marker, file_type in {
                    "word/document.xml": "docx",
                    "xl/workbook.xml": "xlsx",
                    "ppt/presentation.xml": "pptx",
                }.items():
                    if marker in names:
                        return file_type

        except olefile.OleFileError:
            logger.error("Failed to determine file extension, defaulting to txt type.")

        return "txt"
    
    
    def _build_search_results(self, image_info):
        search_results_json = []
        for index, single_image in enumerate(image_info):
            search_result_message = SearchResultTextMessage(
                title=single_image.get("filename", ""),
                url=single_image.get("image_url", ""),
                text=single_image.get("content", ""),
                source_type=single_image.get("source_type", ""),
                filename=single_image.get("filename", ""),
                score_details={},
                cite_index=self.record_ops + index,
                search_type=self.name,
                tool_sign=self.tool_sign,
            )

            search_results_json.append(search_result_message.to_dict())

        return search_results_json