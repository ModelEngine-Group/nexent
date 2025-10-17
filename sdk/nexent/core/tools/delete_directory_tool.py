import json
import logging
import os
import shutil
from typing import Optional
from pydantic import Field
from smolagents.tools import Tool

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import ToolSign, ToolCategory

logger = logging.getLogger("delete_directory_tool")


class DeleteDirectoryTool(Tool):
    """Directory deletion tool for deleting directories and their contents"""
    name = "delete_directory"
    description = "Delete a directory at the specified path. " \
                  "Path should be relative to the workspace (e.g., 'documents/subfolder'). " \
                  "Absolute paths are not allowed for security reasons. " \
                  "This operation is irreversible and will delete the directory and all its contents. " \
                  "Use with caution as deleted directories cannot be recovered."

    inputs = {
        "directory_path": {"type": "string", "description": "Relative path of the directory to delete (e.g., 'documents/subfolder')"}
    }
    output_type = "string"
    category = ToolCategory.FILE.value

    tool_sign = ToolSign.FILE_OPERATION.value  # File operation tool identifier

    def __init__(self, 
                 init_path: str = Field(description="Initial workspace path", default="/mnt/nexent"),
                 observer: MessageObserver = Field(description="Message observer", default=None, exclude=True)):
        """Initialize the DeleteDirectoryTool.
        
        Args:
            init_path (str): Initial workspace path for directory operations. Defaults to "/mnt/nexent".
            observer (MessageObserver, optional): Message observer instance. Defaults to None.
        """
        super().__init__()
        self.init_path = os.path.abspath(init_path)
        self.observer = observer
        self.running_prompt_zh = "正在删除文件夹..."
        self.running_prompt_en = "Deleting directory..."

    def _validate_path(self, directory_path: str) -> str:
        """Validate and resolve directory path within the workspace.
        
        Args:
            directory_path (str): Input directory path
            
        Returns:
            str: Validated absolute path
            
        Raises:
            Exception: If path is outside workspace or invalid
        """
        # Check for absolute path
        if os.path.isabs(directory_path):
            abs_path = os.path.abspath(directory_path)
        else:
            # Treat as relative path from init_path
            abs_path = os.path.abspath(os.path.join(self.init_path, directory_path))
        
        # Normalize path to resolve any '..' or '.' components
        abs_path = os.path.normpath(abs_path)
        
        # Check if the path is within the allowed workspace
        if not abs_path.startswith(self.init_path):
            raise Exception(f"Permission denied: Directory operations are restricted to the workspace directory '{self.init_path}'. "
                          f"Attempted path '{abs_path}' is outside the allowed area. "
                          f"Please use relative paths within the workspace.")
        
        # Additional safety check - don't allow deleting the workspace root
        if abs_path == self.init_path:
            raise Exception(f"Permission denied: Cannot delete the workspace root directory '{self.init_path}'. "
                          f"Please specify a subdirectory within the workspace.")
        
        return abs_path

    def forward(self, directory_path: str) -> str:
        try:
            # Send tool run message if observer is available
            if self.observer:
                running_prompt = self.running_prompt_zh if self.observer.lang == "zh" else self.running_prompt_en
                self.observer.add_message("", ProcessType.TOOL, running_prompt)
                card_content = [{"icon": "folder-minus", "text": f"Deleting directory {directory_path}"}]
                self.observer.add_message("", ProcessType.CARD, json.dumps(card_content, ensure_ascii=False))

            # Validate directory path
            if not directory_path or directory_path.strip() == "":
                raise Exception("Directory path cannot be empty")

            # Validate and resolve path within workspace
            abs_path = self._validate_path(directory_path)
            
            # Check if directory exists
            if not os.path.exists(abs_path):
                raise Exception(f"Directory does not exist: {directory_path}")

            # Check if it's a directory (not a file)
            if not os.path.isdir(abs_path):
                raise Exception(f"Path is not a directory: {directory_path}. Use delete_file tool for files.")

            # Get directory metadata before deletion
            dir_name = os.path.basename(abs_path)
            
            # Count contents before deletion
            total_items = 0
            total_size = 0
            for root, dirs, files in os.walk(abs_path):
                total_items += len(dirs) + len(files)
                for file in files:
                    try:
                        file_path = os.path.join(root, file)
                        total_size += os.path.getsize(file_path)
                    except (OSError, IOError):
                        # Skip files that can't be accessed
                        pass

            # Safety warning for large directories
            if total_items > 100:
                logger.warning(f"Deleting large directory with {total_items} items: {abs_path}")
                if self.observer:
                    warning_msg = f"警告：正在删除包含 {total_items} 个项目的大文件夹" if self.observer.lang == "zh" else f"Warning: Deleting large directory with {total_items} items"
                    self.observer.add_message("", ProcessType.OTHER, warning_msg)

            # Delete the directory and all its contents
            shutil.rmtree(abs_path)

            logger.info(f"Successfully deleted directory: {abs_path}")
            
            # Prepare success message
            # Show relative path in response for better UX
            relative_path = os.path.relpath(abs_path, self.init_path)
            success_msg = {
                "status": "success",
                "directory_path": relative_path,
                "absolute_path": abs_path,
                "directory_name": dir_name,
                "items_deleted": total_items,
                "size_deleted_bytes": total_size,
                "message": f"Directory deleted successfully: {relative_path}"
            }

            return json.dumps(success_msg, ensure_ascii=False)

        except FileNotFoundError as e:
            logger.error(f"Directory not found: {directory_path}, error: {e}")
            error_msg = f"Directory not found: {directory_path}. The directory may have already been deleted or never existed."
            raise Exception(error_msg)
        
        except PermissionError as e:
            logger.error(f"Permission denied when deleting directory: {directory_path}, error: {e}")
            error_msg = f"Permission denied: Cannot delete directory at {directory_path}. Check directory permissions or if files are in use."
            raise Exception(error_msg)
        
        except OSError as e:
            logger.error(f"OS error when deleting directory: {directory_path}, error: {e}")
            error_msg = f"OS error: Cannot delete directory at {directory_path}. {str(e)}"
            raise Exception(error_msg)
        
        except Exception as e:
            logger.error(f"Unexpected error when deleting directory: {directory_path}, error: {e}")
            error_msg = f"Failed to delete directory: {str(e)}"
            raise Exception(error_msg) 