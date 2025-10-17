import json
import logging
import os
from typing import Optional, List, Dict, Any
from pydantic import Field
from smolagents.tools import Tool

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import ToolSign, ToolCategory

logger = logging.getLogger("list_directory_tool")


class ListDirectoryTool(Tool):
    """Directory listing tool for displaying directory contents in tree structure"""
    name = "list_directory"
    description = "List contents of a directory in tree structure format. " \
                  "Path should be relative to the workspace (e.g., 'documents' or '.' for current workspace). " \
                  "Absolute paths are not allowed for security reasons. " \
                  "Returns a hierarchical tree view of files and directories with metadata."

    inputs = {
        "directory_path": {"type": "string", "description": "Relative path of the directory to list (e.g., 'documents' or '.' for workspace root)", "default": ".", "nullable": True},
        "max_depth": {"type": "integer", "description": "Maximum depth to traverse (default: 3, max: 10)", "default": 3, "nullable": True},
        "show_hidden": {"type": "boolean", "description": "Whether to show hidden files/directories (starting with .)", "default": False, "nullable": True},
        "show_size": {"type": "boolean", "description": "Whether to show file sizes", "default": True, "nullable": True}
    }
    output_type = "string"
    category = ToolCategory.FILE.value

    tool_sign = ToolSign.FILE_OPERATION.value  # File operation tool identifier

    def __init__(self, 
                 init_path: str = Field(description="Initial workspace path", default="/mnt/nexent"),
                 observer: MessageObserver = Field(description="Message observer", default=None, exclude=True)):
        """Initialize the ListDirectoryTool.
        
        Args:
            init_path (str): Initial workspace path for directory operations. Defaults to "/mnt/nexent".
            observer (MessageObserver, optional): Message observer instance. Defaults to None.
        """
        super().__init__()
        self.init_path = os.path.abspath(init_path)
        self.observer = observer
        self.running_prompt_zh = "正在列出目录内容..."
        self.running_prompt_en = "Listing directory contents..."

    def _validate_path(self, directory_path: str) -> str:
        """Validate and resolve directory path within the workspace.
        
        Args:
            directory_path (str): Input directory path
            
        Returns:
            str: Validated absolute path
            
        Raises:
            Exception: If path is outside workspace or invalid
        """
        # Handle current directory
        if directory_path == "." or directory_path == "":
            return self.init_path
            
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

    def _format_size(self, size_bytes: int) -> str:
        """Format file size in human readable format."""
        if size_bytes < 1024:
            return f"{size_bytes}B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes/1024:.1f}KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes/(1024*1024):.1f}MB"
        else:
            return f"{size_bytes/(1024*1024*1024):.1f}GB"

    def _build_tree_structure(self, directory_path: str, max_depth: int, show_hidden: bool, 
                            show_size: bool, current_depth: int = 0) -> Dict[str, Any]:
        """Build tree structure recursively.
        
        Args:
            directory_path (str): Absolute path to directory
            max_depth (int): Maximum depth to traverse
            show_hidden (bool): Whether to show hidden files
            show_size (bool): Whether to show file sizes
            current_depth (int): Current recursion depth
            
        Returns:
            Dict containing tree structure
        """
        if current_depth >= max_depth:
            return {"truncated": True, "reason": "max_depth_reached"}
        
        try:
            items = []
            entries = sorted(os.listdir(directory_path))
            
            for entry in entries:
                # Skip hidden files if not requested
                if not show_hidden and entry.startswith('.'):
                    continue
                    
                entry_path = os.path.join(directory_path, entry)
                relative_path = os.path.relpath(entry_path, self.init_path)
                
                try:
                    stat_info = os.stat(entry_path)
                    is_dir = os.path.isdir(entry_path)
                    
                    item = {
                        "name": entry,
                        "path": relative_path,
                        "type": "directory" if is_dir else "file",
                        "permissions": oct(stat_info.st_mode)[-3:],
                        "modified": stat_info.st_mtime
                    }
                    
                    if is_dir:
                        # Recursively get subdirectory contents
                        if current_depth + 1 < max_depth:
                            subtree = self._build_tree_structure(
                                entry_path, max_depth, show_hidden, show_size, current_depth + 1
                            )
                            if "children" in subtree:
                                item["children"] = subtree["children"]
                            elif "truncated" in subtree:
                                item["children"] = []
                                item["truncated"] = True
                        else:
                            item["children"] = []
                            item["truncated"] = True
                            
                        # Count items in directory
                        try:
                            dir_entries = os.listdir(entry_path)
                            if not show_hidden:
                                dir_entries = [e for e in dir_entries if not e.startswith('.')]
                            item["item_count"] = len(dir_entries)
                        except PermissionError:
                            item["item_count"] = "Permission denied"
                    else:
                        # File size
                        if show_size:
                            item["size"] = stat_info.st_size
                            item["size_formatted"] = self._format_size(stat_info.st_size)
                    
                    items.append(item)
                    
                except (OSError, PermissionError) as e:
                    # Add entry with error info
                    items.append({
                        "name": entry,
                        "path": relative_path,
                        "type": "unknown",
                        "error": str(e)
                    })
                    
            return {"children": items}
            
        except PermissionError:
            return {"error": "Permission denied"}
        except OSError as e:
            return {"error": str(e)}

    def _format_tree_display(self, tree_data: Dict[str, Any], show_size: bool, 
                           prefix: str = "", is_last: bool = True) -> List[str]:
        """Format tree structure for display.
        
        Args:
            tree_data (Dict): Tree structure data
            show_size (bool): Whether to show file sizes
            prefix (str): Current line prefix
            is_last (bool): Whether this is the last item in current level
            
        Returns:
            List of formatted lines
        """
        lines = []
        
        if "children" not in tree_data:
            return lines
            
        children = tree_data["children"]
        
        for i, item in enumerate(children):
            is_last_child = (i == len(children) - 1)
            
            # Choose the appropriate tree characters
            if is_last_child:
                current_prefix = prefix + "└── "
                next_prefix = prefix + "    "
            else:
                current_prefix = prefix + "├── "
                next_prefix = prefix + "│   "
            
            # Format the item line
            line = current_prefix + item["name"]
            
            if item["type"] == "directory":
                line += "/"
                if "item_count" in item and isinstance(item["item_count"], int):
                    line += f" ({item['item_count']} items)"
                if item.get("truncated"):
                    line += " [...]"
            elif item["type"] == "file" and show_size and "size_formatted" in item:
                line += f" ({item['size_formatted']})"
            elif "error" in item:
                line += f" [ERROR: {item['error']}]"
                
            lines.append(line)
            
            # Recursively add children
            if item["type"] == "directory" and "children" in item:
                child_lines = self._format_tree_display(
                    {"children": item["children"]}, show_size, next_prefix, is_last_child
                )
                lines.extend(child_lines)
                
        return lines

    def forward(self, directory_path: str = ".", max_depth: int = 3, 
               show_hidden: bool = False, show_size: bool = True) -> str:
        try:
            # Send tool run message if observer is available
            if self.observer:
                running_prompt = self.running_prompt_zh if self.observer.lang == "zh" else self.running_prompt_en
                self.observer.add_message("", ProcessType.TOOL, running_prompt)
                card_content = [{"icon": "folder-tree", "text": f"Listing directory {directory_path}"}]
                self.observer.add_message("", ProcessType.CARD, json.dumps(card_content, ensure_ascii=False))

            # Validate directory path
            if directory_path is None:
                directory_path = "."

            # Validate max_depth
            if max_depth > 10:
                max_depth = 10
                logger.warning("Max depth limited to 10 for performance reasons")
            elif max_depth < 1:
                max_depth = 1

            # Validate and resolve path within workspace
            abs_path = self._validate_path(directory_path)
            
            # Check if directory exists
            if not os.path.exists(abs_path):
                raise Exception(f"Directory does not exist: {directory_path}")

            # Check if it's a directory
            if not os.path.isdir(abs_path):
                raise Exception(f"Path is not a directory: {directory_path}")

            logger.info(f"Listing directory: {abs_path} with max_depth={max_depth}")
            
            # Build tree structure
            tree_data = self._build_tree_structure(abs_path, max_depth, show_hidden, show_size)
            
            if "error" in tree_data:
                raise Exception(f"Failed to read directory: {tree_data['error']}")
            
            # Format tree for display
            relative_path = os.path.relpath(abs_path, self.init_path)
            if relative_path == ".":
                root_name = "📁 workspace"
            else:
                root_name = f"📁 {relative_path}"
                
            tree_lines = [root_name]
            if "children" in tree_data:
                formatted_lines = self._format_tree_display(tree_data, show_size)
                tree_lines.extend(formatted_lines)
            
            # Count total items
            total_files = 0
            total_dirs = 0
            total_size = 0
            
            def count_items(data):
                nonlocal total_files, total_dirs, total_size
                if "children" in data:
                    for item in data["children"]:
                        if item["type"] == "file":
                            total_files += 1
                            if "size" in item:
                                total_size += item["size"]
                        elif item["type"] == "directory":
                            total_dirs += 1
                            if "children" in item:
                                count_items({"children": item["children"]})
            
            count_items(tree_data)
            
            # Prepare success message
            tree_display = "\n".join(tree_lines)
            
            success_msg = {
                "status": "success",
                "directory_path": relative_path,
                "absolute_path": abs_path,
                "tree_display": tree_display,
                "tree_data": tree_data,
                "summary": {
                    "total_files": total_files,
                    "total_directories": total_dirs,
                    "total_size_bytes": total_size,
                    "total_size_formatted": self._format_size(total_size) if total_size > 0 else "0B",
                    "max_depth": max_depth,
                    "show_hidden": show_hidden
                },
                "message": f"Directory listing completed for {relative_path}"
            }

            return json.dumps(success_msg, ensure_ascii=False)

        except PermissionError as e:
            logger.error(f"Permission denied when listing directory: {directory_path}, error: {e}")
            error_msg = f"Permission denied: Cannot access directory at {directory_path}. Check directory permissions."
            raise Exception(error_msg)
        
        except OSError as e:
            logger.error(f"OS error when listing directory: {directory_path}, error: {e}")
            error_msg = f"OS error: Cannot access directory at {directory_path}. {str(e)}"
            raise Exception(error_msg)
        
        except Exception as e:
            logger.error(f"Unexpected error when listing directory: {directory_path}, error: {e}")
            error_msg = f"Failed to list directory: {str(e)}"
            raise Exception(error_msg) 