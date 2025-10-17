import json
import logging
import os
from typing import Optional
from pydantic import Field
from smolagents.tools import Tool

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import ToolSign, ToolCategory

logger = logging.getLogger("read_file_tool")


class ReadFileTool(Tool):
    """File reading tool for reading file contents"""
    name = "read_file"
    description = "Read content from a file at the specified path. " \
                  "Path should be relative to the workspace (e.g., 'documents/file.txt'). " \
                  "Absolute paths are not allowed for security reasons. " \
                  "Supports custom encoding, defaults to utf-8. " \
                  "Returns the file content as a string along with file metadata."

    inputs = {
        "file_path": {"type": "string", "description": "Relative path of the file to read (e.g., 'documents/file.txt')"},
        "encoding": {"type": "string", "description": "File encoding, defaults to utf-8", "default": "utf-8", "nullable": True}
    }
    output_type = "string"
    category = ToolCategory.FILE.value

    tool_sign = ToolSign.FILE_OPERATION.value  # File operation tool identifier

    def __init__(self, 
                 init_path: str = Field(description="Initial workspace path", default="/mnt/nexent"),
                 observer: MessageObserver = Field(description="Message observer", default=None, exclude=True)):
        """Initialize the ReadFileTool.
        
        Args:
            init_path (str): Initial workspace path for file operations. Defaults to "/mnt/nexent".
            observer (MessageObserver, optional): Message observer instance. Defaults to None.
        """
        super().__init__()
        self.init_path = os.path.abspath(init_path)
        self.observer = observer
        self.running_prompt_zh = "正在读取文件..."
        self.running_prompt_en = "Reading file..."

    def _validate_path(self, file_path: str) -> str:
        """Validate and resolve file path within the workspace.
        
        Args:
            file_path (str): Input file path
            
        Returns:
            str: Validated absolute path
            
        Raises:
            Exception: If path is outside workspace or invalid
        """
        # Check for absolute path
        if os.path.isabs(file_path):
            abs_path = os.path.abspath(file_path)
        else:
            # Treat as relative path from init_path
            abs_path = os.path.abspath(os.path.join(self.init_path, file_path))
        
        # Normalize path to resolve any '..' or '.' components
        abs_path = os.path.normpath(abs_path)
        
        # Check if the path is within the allowed workspace
        if not abs_path.startswith(self.init_path):
            raise Exception(f"Permission denied: File operations are restricted to the workspace directory '{self.init_path}'. "
                          f"Attempted path '{abs_path}' is outside the allowed area. "
                          f"Please use relative paths within the workspace.")
        
        return abs_path

    def forward(self, file_path: str, encoding: str = "utf-8") -> str:
        try:
            # Send tool run message if observer is available
            if self.observer:
                running_prompt = self.running_prompt_zh if self.observer.lang == "zh" else self.running_prompt_en
                self.observer.add_message("", ProcessType.TOOL, running_prompt)
                card_content = [{"icon": "file-text", "text": f"Reading {file_path}"}]
                self.observer.add_message("", ProcessType.CARD, json.dumps(card_content, ensure_ascii=False))

            # Validate file path
            if not file_path or file_path.strip() == "":
                raise Exception("File path cannot be empty")

            # Validate and resolve path within workspace
            abs_path = self._validate_path(file_path)
            
            # Check if file exists
            if not os.path.exists(abs_path):
                raise Exception(f"File does not exist: {abs_path}")

            # Check if it's a file (not a directory)
            if not os.path.isfile(abs_path):
                raise Exception(f"Path is not a file: {abs_path}")

            # Get file metadata
            file_stats = os.stat(abs_path)
            file_size = file_stats.st_size

            # Check if file is too large (optional safety check - 10MB limit)
            max_size = 10 * 1024 * 1024  # 10MB
            if file_size > max_size:
                logger.warning(f"Large file detected: {file_size} bytes")
                if self.observer:
                    warning_msg = f"大文件警告: {file_size} 字节" if self.observer.lang == "zh" else f"Large file warning: {file_size} bytes"
                    self.observer.add_message("", ProcessType.OTHER, warning_msg)

            # Read file content
            with open(abs_path, 'r', encoding=encoding) as f:
                content = f.read()

            logger.info(f"Successfully read file: {abs_path} with encoding: {encoding}")
            
            # Prepare success message
            # Show relative path in response for better UX
            relative_path = os.path.relpath(abs_path, self.init_path)
            success_msg = {
                "status": "success",
                "file_path": relative_path,
                "absolute_path": abs_path,
                "content": content,
                "content_length": len(content),
                "file_size_bytes": file_size,
                "encoding": encoding,
                "lines_count": content.count('\n') + 1 if content else 0,
                "message": f"File read successfully from {relative_path}"
            }

            return json.dumps(success_msg, ensure_ascii=False)

        except FileNotFoundError as e:
            logger.error(f"File not found: {file_path}, error: {e}")
            error_msg = f"File not found: {file_path}. Please check if the file exists."
            raise Exception(error_msg)
        
        except PermissionError as e:
            logger.error(f"Permission denied when reading file: {file_path}, error: {e}")
            error_msg = f"Permission denied: Cannot read file at {file_path}. Check file permissions."
            raise Exception(error_msg)
        
        except UnicodeDecodeError as e:
            logger.error(f"Encoding error when reading file: {file_path}, encoding: {encoding}, error: {e}")
            error_msg = f"Encoding error: Cannot read file with {encoding} encoding. Try a different encoding or check if the file is binary."
            raise Exception(error_msg)
        
        except OSError as e:
            logger.error(f"OS error when reading file: {file_path}, error: {e}")
            error_msg = f"OS error: Cannot read file at {file_path}. {str(e)}"
            raise Exception(error_msg)
        
        except Exception as e:
            logger.error(f"Unexpected error when reading file: {file_path}, error: {e}")
            error_msg = f"Failed to read file: {str(e)}"
            raise Exception(error_msg) 