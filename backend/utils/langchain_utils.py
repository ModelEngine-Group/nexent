import importlib.util
import logging
import os
from typing import Any, Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default path for LangChain tools
LANGCHAIN_TOOLS_DIR = os.path.abspath(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tool_collection",
    "langchain"
))


def _is_langchain_tool(obj) -> bool:
    from langchain_core.tools import BaseTool
    return isinstance(obj, BaseTool)


def discover_langchain_modules(
    directory: str = LANGCHAIN_TOOLS_DIR,
    filter_func: Optional[Callable[[Any], bool]] = _is_langchain_tool
) -> List[Tuple[Any, str]]:
    """
    Discover and import Python modules that may contain LangChain tools from a directory.

    Args:
        directory: Path to directory containing Python modules to scan
                  Defaults to the standard LangChain tools directory
        filter_func: Optional function to filter discovered objects
                     If provided, only objects where filter_func(obj) is True are returned

    Returns:
        List of tuples (discovered_object, source_filename) that pass the filter function
    """
    discovered_objects = []

    if not os.path.isdir(directory):
        logger.warning(f"Directory not found: {directory}")
        return discovered_objects

    for filename in os.listdir(directory):
        # Skip non-python files and dunder modules
        if not filename.endswith(".py") or filename.startswith("__"):
            continue

        module_path = os.path.join(directory, filename)
        module_name = f"langchain_tool_{filename[:-3]}"  # unique name

        try:
            spec = importlib.util.spec_from_file_location(
                module_name, module_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            else:
                logger.warning(f"Failed to load spec for {module_path}")
                continue

            # Process module attributes
            for attr_name in dir(module):
                if attr_name.startswith("__"):
                    continue

                obj = getattr(module, attr_name)

                # Apply filter if provided, otherwise include all objects
                if filter_func(obj):
                    discovered_objects.append((obj, filename))

        except Exception as e:
            logger.error(f"Error processing module {filename}: {e}")

    return discovered_objects
