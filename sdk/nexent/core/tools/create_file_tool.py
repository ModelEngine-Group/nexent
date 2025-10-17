import json
import logging
import os
from typing import Optional
from pydantic import Field
from smolagents.tools import Tool

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import ToolSign, ToolCategory

logger = logging.getLogger("create_file_tool")


class CreateFileTool(Tool):
    """File creation tool for creating files and writing content"""
    name = "create_file"
    description = "Create a file at the specified path and write content to it. " \
                  "Path should be relative to the workspace (e.g., 'documents/file.txt'). " \
                  "Absolute paths are not allowed for security reasons. " \
                  "If content is empty, creates an empty file. " \
                  "Supports custom encoding, defaults to utf-8. " \
                  "Will create parent directories if they don't exist."

    inputs = {
        "file_path": {"type": "string", "description": "Relative path where the file should be created (e.g., 'documents/file.txt')"},
        "content": {"type": "string", "description": "Content to write to the file. If empty, creates an empty file", "nullable": True},
        "encoding": {"type": "string", "description": "File encoding, defaults to utf-8", "default": "utf-8", "nullable": True}
    }
    output_type = "string"
    category = ToolCategory.FILE.value

    tool_sign = ToolSign.FILE_OPERATION.value  # File operation tool identifier

    def __init__(self, 
                 init_path: str = Field(description="Initial workspace path", default="/mnt/nexent"),
                 observer: MessageObserver = Field(description="Message observer", default=None, exclude=True)):
        """Initialize the CreateFileTool.
        
        Args:
            init_path (str): Initial workspace path for file operations. Defaults to "/mnt/nexent".
            observer (MessageObserver, optional): Message observer instance. Defaults to None.
        """
        super().__init__()
        self.init_path = os.path.abspath(init_path)
        self.observer = observer
        self.running_prompt_zh = "正在创建文件..."
        self.running_prompt_en = "Creating file..."

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

    def forward(self, file_path: str, content: str = "", encoding: str = "utf-8") -> str:
        try:
            # Send tool run message if observer is available
            if self.observer:
                running_prompt = self.running_prompt_zh if self.observer.lang == "zh" else self.running_prompt_en
                self.observer.add_message("", ProcessType.TOOL, running_prompt)
                card_content = [{"icon": "file-plus", "text": f"Creating {file_path}"}]
                self.observer.add_message("", ProcessType.CARD, json.dumps(card_content, ensure_ascii=False))

            # Validate file path
            if not file_path or file_path.strip() == "":
                raise Exception("File path cannot be empty")

            # Validate and resolve path within workspace
            abs_path = self._validate_path(file_path)
            
            # Create parent directories if they don't exist
            parent_dir = os.path.dirname(abs_path)
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)
                logger.info(f"Created parent directories: {parent_dir}")

            # Check if file already exists
            if os.path.exists(abs_path):
                logger.warning(f"File already exists: {abs_path}")
                if self.observer:
                    warning_msg = f"文件已存在，将覆盖: {abs_path}" if self.observer.lang == "zh" else f"File already exists, will overwrite: {abs_path}"
                    self.observer.add_message("", ProcessType.OTHER, warning_msg)

            # Write content to file
            with open(abs_path, 'w', encoding=encoding) as f:
                f.write(content if content is not None else "")

            logger.info(f"Successfully created file: {abs_path} with encoding: {encoding}")
            
            # Prepare success message
            file_size = os.path.getsize(abs_path)
            # Show relative path in response for better UX
            relative_path = os.path.relpath(abs_path, self.init_path)
            success_msg = {
                "status": "success",
                "file_path": relative_path,
                "absolute_path": abs_path,
                "content_length": len(content) if content else 0,
                "file_size_bytes": file_size,
                "encoding": encoding,
                "message": f"File created successfully at {relative_path}"
            }

            return json.dumps(success_msg, ensure_ascii=False)

        except PermissionError as e:
            logger.error(f"Permission denied when creating file: {file_path}, error: {e}")
            error_msg = f"Permission denied: Cannot create file at {file_path}. Check file permissions."
            raise Exception(error_msg)
        
        except UnicodeEncodeError as e:
            logger.error(f"Encoding error when creating file: {file_path}, encoding: {encoding}, error: {e}")
            error_msg = f"Encoding error: Cannot write content with {encoding} encoding. Try a different encoding."
            raise Exception(error_msg)
        
        except OSError as e:
            logger.error(f"OS error when creating file: {file_path}, error: {e}")
            error_msg = f"OS error: Cannot create file at {file_path}. {str(e)}"
            raise Exception(error_msg)
        
        except Exception as e:
            logger.error(f"Unexpected error when creating file: {file_path}, error: {e}")
            error_msg = f"Failed to create file: {str(e)}"
            raise Exception(error_msg) 