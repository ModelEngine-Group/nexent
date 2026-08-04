import importlib
import inspect
from typing import List, Dict


def get_local_tools_classes() -> List[type]:
    """
    Get all tool classes from the nexent.core.tools package.

    Tools whose class-level ``category`` attribute is one of the SDK-internal
    categories (see ``ToolCategory``) are filtered out so they do not appear
    in the user-facing tool picker. These tools are injected by the SDK
    itself at agent construction time and must not be user-configurable.

    Returns:
        List of tool class objects
    """
    tools_package = importlib.import_module('nexent.core.tools')
    tools_classes = []
    for name in dir(tools_package):
        obj = getattr(tools_package, name)
        if inspect.isclass(obj) and not _is_internal_tool(obj):
            tools_classes.append(obj)
    return tools_classes


def _is_internal_tool(tool_class: type) -> bool:
    """Return True if the tool class is SDK-internal and must be hidden from
    user-facing tool pickers.

    Tools opt-in by setting ``category = ToolCategory.<INTERNAL>.value``
    on the class body. Today only ``ToolCategory.PLANNING`` is internal;
    new internal categories (e.g. future tracing / debug tools) can be
    added here without touching any tool code.
    """
    try:
        from nexent.core.utils.tools_common_message import ToolCategory
    except ImportError:
        return False
    category = getattr(tool_class, "category", None)
    if category is None:
        return False
    internal_categories = {ToolCategory.PLANNING.value}
    return category in internal_categories


def get_local_tools_description_zh() -> Dict[str, Dict]:
    """
    Get description_zh for all local tools from SDK (not persisted to DB).

    Returns:
        Dict mapping tool name to {"description_zh": ..., "params": [...], "inputs": {...}}
    """
    tools_classes = get_local_tools_classes()
    result = {}
    for tool_class in tools_classes:
        tool_name = getattr(tool_class, 'name')

        description_zh = getattr(tool_class, 'description_zh', None)

        init_param_descriptions = getattr(tool_class, 'init_param_descriptions', {})

        init_params_list = []
        sig = inspect.signature(tool_class.__init__)
        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue

            # Check if parameter has a default value and if it should be excluded
            if param.default != inspect.Parameter.empty:
                if hasattr(param.default, 'exclude') and param.default.exclude:
                    continue

            # Note: Pydantic Field doesn't have description_zh attribute
            param_description_zh = getattr(param.default, 'description_zh', None) if hasattr(param.default, 'description_zh') else None

            if param_description_zh is None and param_name in init_param_descriptions:
                param_description_zh = init_param_descriptions[param_name].get('description_zh')

            init_params_list.append({
                "name": param_name,
                "description_zh": param_description_zh
            })

        # Store complete inputs definition for runtime alignment
        tool_inputs = getattr(tool_class, 'inputs', {})
        inputs_complete = {}
        if isinstance(tool_inputs, dict):
            for key, value in tool_inputs.items():
                if isinstance(value, dict):
                    inputs_complete[key] = value

        result[tool_name] = {
            "description_zh": description_zh,
            "params": init_params_list,
            "inputs": inputs_complete
        }
    return result
