import importlib
import inspect
from typing import List, Dict


def get_local_tools_classes() -> List[type]:
    """
    Get all tool classes from the nexent.core.tools package

    Returns:
        List of tool class objects
    """
    tools_package = importlib.import_module('nexent.core.tools')
    tools_classes = []
    for name in dir(tools_package):
        obj = getattr(tools_package, name)
        if inspect.isclass(obj):
            tools_classes.append(obj)
    return tools_classes


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

        # Get tool-level description_zh
        description_zh = getattr(tool_class, 'description_zh', None)

        # Get class-level init_param_descriptions for fallback
        init_param_descriptions = getattr(tool_class, 'init_param_descriptions', {})

        # Get param-level description_zh
        init_params_list = []
        sig = inspect.signature(tool_class.__init__)
        for param_name, param in sig.parameters.items():
            if param_name == "self" or param.default.exclude:
                continue

            # First try to get from param.default.description_zh (FieldInfo)
            param_description_zh = param.default.description_zh if hasattr(param.default, 'description_zh') else None

            # Fallback to init_param_descriptions if not found
            if param_description_zh is None and param_name in init_param_descriptions:
                param_description_zh = init_param_descriptions[param_name].get('description_zh')

            init_params_list.append({
                "name": param_name,
                "description_zh": param_description_zh
            })

        # Get inputs description_zh
        tool_inputs = getattr(tool_class, 'inputs', {})
        inputs_description_zh = {}
        if isinstance(tool_inputs, dict):
            for key, value in tool_inputs.items():
                if isinstance(value, dict) and value.get("description_zh"):
                    inputs_description_zh[key] = {
                        "description_zh": value.get("description_zh")
                    }

        result[tool_name] = {
            "description_zh": description_zh,
            "params": init_params_list,
            "inputs": inputs_description_zh
        }
    return result
