import json
import logging
import os
from typing import Optional
from pydantic import Field
from smolagents.tools import Tool

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import ToolSign, ToolCategory

logger = logging.getLogger("create_directory_tool")


class CreateDirectoryTool(Tool):
    """Directory creation tool for creating directories"""
    name = "create_directory"
    description = "Create a directory at the specified path. " \
                  "Path should be relative to the workspace (e.g., 'documents/subfolder'). " \
                  "Absolute paths are not allowed for security reasons. " \
                  "Will create parent directories if they don't exist. " \
                  "If directory already exists, operation will succeed without error."

    inputs = {
        "directory_path": {"type": "string", "description": "Relative path where the directory should be created (e.g., 'documents/subfolder')"},
        "permissions": {"type": "string", "description": "Directory permissions in octal format (e.g., '755')", "default": "755", "nullable": True}
    }
    output_type = "string"
    category = ToolCategory.FILE.value

    tool_sign = ToolSign.FILE_OPERATION.value  # File operation tool identifier

    def __init__(self, 
                 init_path: str = Field(description="Initial workspace path", default="/mnt/nexent"),
                 observer: MessageObserver = Field(description="Message observer", default=None, exclude=True)):
        """Initialize the CreateDirectoryTool.
        
        Args:
            init_path (str): Initial workspace path for directory operations. Defaults to "/mnt/nexent".
            observer (MessageObserver, optional): Message observer instance. Defaults to None.
        """
        super().__init__()
        self.init_path = os.path.abspath(init_path)
        self.observer = observer
        self.running_prompt_zh = "正在创建文件夹..."
        self.running_prompt_en = "Creating directory..."

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
        
        return abs_path

    def forward(self, directory_path: str, permissions: str = "755") -> str:
        try:
            # Send tool run message if observer is available
            if self.observer:
                running_prompt = self.running_prompt_zh if self.observer.lang == "zh" else self.running_prompt_en
                self.observer.add_message("", ProcessType.TOOL, running_prompt)
                card_content = [{"icon": "folder-plus", "text": f"Creating directory {directory_path}"}]
                self.observer.add_message("", ProcessType.CARD, json.dumps(card_content, ensure_ascii=False))

            # Validate directory path
            if not directory_path or directory_path.strip() == "":
                raise Exception("Directory path cannot be empty")

            # Validate and resolve path within workspace
            abs_path = self._validate_path(directory_path)

            # Validate permissions format
            try:
                octal_permissions = int(permissions, 8)
            except ValueError:
                raise Exception(f"Invalid permissions format: '{permissions}'. Please use octal format (e.g., '755', '644').")

            # Check if directory already exists
            already_exists = os.path.exists(abs_path)
            if already_exists:
                if not os.path.isdir(abs_path):
                    raise Exception(f"Path already exists but is not a directory: {directory_path}")
                logger.info(f"Directory already exists: {abs_path}")
                if self.observer:
                    info_msg = f"目录已存在: {directory_path}" if self.observer.lang == "zh" else f"Directory already exists: {directory_path}"
                    self.observer.add_message("", ProcessType.OTHER, info_msg)

            # Create directory with parents if they don't exist
            os.makedirs(abs_path, mode=octal_permissions, exist_ok=True)

            # Set permissions explicitly (makedirs mode can be affected by umask)
            os.chmod(abs_path, octal_permissions)

            logger.info(f"Successfully created/verified directory: {abs_path} with permissions: {permissions}")
            
            # Prepare success message
            # Show relative path in response for better UX
            relative_path = os.path.relpath(abs_path, self.init_path)
            success_msg = {
                "status": "success",
                "directory_path": relative_path,
                "absolute_path": abs_path,
                "permissions": permissions,
                "already_existed": already_exists,
                "message": f"Directory {'verified' if already_exists else 'created successfully'} at {relative_path}"
            }

            return json.dumps(success_msg, ensure_ascii=False)

        except PermissionError as e:
            logger.error(f"Permission denied when creating directory: {directory_path}, error: {e}")
            error_msg = f"Permission denied: Cannot create directory at {directory_path}. Check directory permissions."
            raise Exception(error_msg)
        
        except OSError as e:
            logger.error(f"OS error when creating directory: {directory_path}, error: {e}")
            error_msg = f"OS error: Cannot create directory at {directory_path}. {str(e)}"
            raise Exception(error_msg)
        
        except Exception as e:
            logger.error(f"Unexpected error when creating directory: {directory_path}, error: {e}")
            error_msg = f"Failed to create directory: {str(e)}"
            raise Exception(error_msg) 