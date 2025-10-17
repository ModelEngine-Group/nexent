import json
import logging
import os
import shutil
from typing import Optional
from pydantic import Field
from smolagents.tools import Tool

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import ToolSign, ToolCategory

logger = logging.getLogger("move_item_tool")


class MoveItemTool(Tool):
    """Move tool for moving files or directories to a new location"""
    name = "move_item"
    description = "Move a file or directory from source path to destination path. " \
                  "Both paths should be relative to the workspace (e.g., 'documents/file.txt' to 'backup/file.txt'). " \
                  "Absolute paths are not allowed for security reasons. " \
                  "Works for both files and directories. If destination directory doesn't exist, it will be created. " \
                  "If destination already exists, the operation will fail to prevent overwriting."

    inputs = {
        "source_path": {"type": "string", "description": "Relative path of the source file or directory to move (e.g., 'documents/file.txt')"},
        "destination_path": {"type": "string", "description": "Relative path of the destination (e.g., 'backup/file.txt')"}
    }
    output_type = "string"
    category = ToolCategory.FILE.value

    tool_sign = ToolSign.FILE_OPERATION.value  # File operation tool identifier

    def __init__(self, 
                 init_path: str = Field(description="Initial workspace path", default="/mnt/nexent"),
                 observer: MessageObserver = Field(description="Message observer", default=None, exclude=True)):
        """Initialize the MoveItemTool.
        
        Args:
            init_path (str): Initial workspace path for file operations. Defaults to "/mnt/nexent".
            observer (MessageObserver, optional): Message observer instance. Defaults to None.
        """
        super().__init__()
        self.init_path = os.path.abspath(init_path)
        self.observer = observer
        self.running_prompt_zh = "正在移动文件/文件夹..."
        self.running_prompt_en = "Moving file/directory..."

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

    def forward(self, source_path: str, destination_path: str) -> str:
        try:
            # Send tool run message if observer is available
            if self.observer:
                running_prompt = self.running_prompt_zh if self.observer.lang == "zh" else self.running_prompt_en
                self.observer.add_message("", ProcessType.TOOL, running_prompt)
                card_content = [{"icon": "move", "text": f"Moving {source_path} to {destination_path}"}]
                self.observer.add_message("", ProcessType.CARD, json.dumps(card_content, ensure_ascii=False))

            # Validate paths
            if not source_path or source_path.strip() == "":
                raise Exception("Source path cannot be empty")
            if not destination_path or destination_path.strip() == "":
                raise Exception("Destination path cannot be empty")

            # Validate and resolve paths within workspace
            abs_source_path = self._validate_path(source_path)
            abs_destination_path = self._validate_path(destination_path)
            
            # Check if source exists
            if not os.path.exists(abs_source_path):
                raise Exception(f"Source does not exist: {source_path}")

            # Check if destination already exists
            if os.path.exists(abs_destination_path):
                raise Exception(f"Destination already exists: {destination_path}. Move operation cancelled to prevent overwriting.")

            # Get source metadata before moving
            source_name = os.path.basename(abs_source_path)
            is_directory = os.path.isdir(abs_source_path)
            
            # Calculate size before moving
            if is_directory:
                total_size = 0
                total_items = 0
                for root, dirs, files in os.walk(abs_source_path):
                    total_items += len(dirs) + len(files)
                    for file in files:
                        try:
                            file_path = os.path.join(root, file)
                            total_size += os.path.getsize(file_path)
                        except (OSError, IOError):
                            pass
            else:
                total_size = os.path.getsize(abs_source_path)
                total_items = 1

            # Create destination parent directory if it doesn't exist
            dest_parent = os.path.dirname(abs_destination_path)
            if dest_parent and not os.path.exists(dest_parent):
                os.makedirs(dest_parent, exist_ok=True)
                logger.info(f"Created destination parent directory: {dest_parent}")

            # Perform the move operation
            shutil.move(abs_source_path, abs_destination_path)

            logger.info(f"Successfully moved {'directory' if is_directory else 'file'}: {abs_source_path} -> {abs_destination_path}")
            
            # Prepare success message
            # Show relative paths in response for better UX
            relative_source = os.path.relpath(abs_source_path, self.init_path)
            relative_destination = os.path.relpath(abs_destination_path, self.init_path)
            
            success_msg = {
                "status": "success",
                "source_path": relative_source,
                "destination_path": relative_destination,
                "absolute_source_path": abs_source_path,
                "absolute_destination_path": abs_destination_path,
                "item_name": source_name,
                "is_directory": is_directory,
                "size_bytes": total_size,
                "items_moved": total_items if is_directory else 1,
                "message": f"{'Directory' if is_directory else 'File'} moved successfully from {relative_source} to {relative_destination}"
            }

            return json.dumps(success_msg, ensure_ascii=False)

        except FileNotFoundError as e:
            logger.error(f"Source not found: {source_path}, error: {e}")
            error_msg = f"Source not found: {source_path}. The file or directory may have already been moved or deleted."
            raise Exception(error_msg)
        
        except PermissionError as e:
            logger.error(f"Permission denied when moving: {source_path} -> {destination_path}, error: {e}")
            error_msg = f"Permission denied: Cannot move from {source_path} to {destination_path}. Check file/directory permissions."
            raise Exception(error_msg)
        
        except OSError as e:
            logger.error(f"OS error when moving: {source_path} -> {destination_path}, error: {e}")
            error_msg = f"OS error: Cannot move from {source_path} to {destination_path}. {str(e)}"
            raise Exception(error_msg)
        
        except Exception as e:
            logger.error(f"Unexpected error when moving: {source_path} -> {destination_path}, error: {e}")
            error_msg = f"Failed to move item: {str(e)}"
            raise Exception(error_msg) 