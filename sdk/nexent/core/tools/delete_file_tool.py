import json
import logging
import os
from typing import Optional
from pydantic import Field
from smolagents.tools import Tool

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import ToolSign, ToolCategory

logger = logging.getLogger("delete_file_tool")


class DeleteFileTool(Tool):
    """File deletion tool for deleting a single file"""
    name = "delete_file"
    description = "Delete a single file at the specified path. " \
                  "Path should be relative to the workspace (e.g., 'documents/file.txt'). " \
                  "Absolute paths are not allowed for security reasons. " \
                  "This operation is irreversible and only works on individual files, not directories. " \
                  "Use with caution as deleted files cannot be recovered."

    inputs = {
        "file_path": {"type": "string", "description": "Relative path of the file to delete (e.g., 'documents/file.txt')"}
    }
    output_type = "string"
    category = ToolCategory.FILE.value

    tool_sign = ToolSign.FILE_OPERATION.value  # File operation tool identifier

    def __init__(self, 
                 init_path: str = Field(description="Initial workspace path", default="/mnt/nexent"),
                 observer: MessageObserver = Field(description="Message observer", default=None, exclude=True)):
        """Initialize the DeleteFileTool.
        
        Args:
            init_path (str): Initial workspace path for file operations. Defaults to "/mnt/nexent".
            observer (MessageObserver, optional): Message observer instance. Defaults to None.
        """
        super().__init__()
        self.init_path = os.path.abspath(init_path)
        self.observer = observer
        self.running_prompt_zh = "正在删除文件..."
        self.running_prompt_en = "Deleting file..."

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

    def forward(self, file_path: str) -> str:
        try:
            # Send tool run message if observer is available
            if self.observer:
                running_prompt = self.running_prompt_zh if self.observer.lang == "zh" else self.running_prompt_en
                self.observer.add_message("", ProcessType.TOOL, running_prompt)
                card_content = [{"icon": "trash", "text": f"Deleting {file_path}"}]
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
                raise Exception(f"Path is not a file: {abs_path}. This tool only deletes files, not directories.")

            # Get file metadata before deletion
            file_stats = os.stat(abs_path)
            file_size = file_stats.st_size
            file_name = os.path.basename(abs_path)

            # Safety check for important system files
            protected_patterns = ['.env', 'config', 'passwd', 'shadow', 'hosts']
            if any(pattern in file_name.lower() for pattern in protected_patterns):
                logger.warning(f"Attempting to delete potentially important file: {abs_path}")
                if self.observer:
                    warning_msg = f"警告：正在删除可能重要的文件: {file_name}" if self.observer.lang == "zh" else f"Warning: Deleting potentially important file: {file_name}"
                    self.observer.add_message("", ProcessType.OTHER, warning_msg)

            # Delete the file
            os.remove(abs_path)

            logger.info(f"Successfully deleted file: {abs_path}")
            
            # Prepare success message
            # Show relative path in response for better UX
            relative_path = os.path.relpath(abs_path, self.init_path)
            success_msg = {
                "status": "success",
                "file_path": relative_path,
                "absolute_path": abs_path,
                "file_name": file_name,
                "file_size_bytes": file_size,
                "message": f"File deleted successfully: {relative_path}"
            }

            return json.dumps(success_msg, ensure_ascii=False)

        except FileNotFoundError as e:
            logger.error(f"File not found: {file_path}, error: {e}")
            error_msg = f"File not found: {file_path}. The file may have already been deleted or never existed."
            raise Exception(error_msg)
        
        except PermissionError as e:
            logger.error(f"Permission denied when deleting file: {file_path}, error: {e}")
            error_msg = f"Permission denied: Cannot delete file at {file_path}. Check file permissions or if the file is in use."
            raise Exception(error_msg)
        
        except IsADirectoryError as e:
            logger.error(f"Attempted to delete directory: {file_path}, error: {e}")
            error_msg = f"Cannot delete directory: {file_path}. This tool only deletes individual files."
            raise Exception(error_msg)
        
        except OSError as e:
            logger.error(f"OS error when deleting file: {file_path}, error: {e}")
            error_msg = f"OS error: Cannot delete file at {file_path}. {str(e)}"
            raise Exception(error_msg)
        
        except Exception as e:
            logger.error(f"Unexpected error when deleting file: {file_path}, error: {e}")
            error_msg = f"Failed to delete file: {str(e)}"
            raise Exception(error_msg) 