"""Keep runtime-owned AIDP connection state out of portable agent settings."""

from copy import deepcopy


class AgentToolImportError(ValueError):
    """An exported tool is incompatible with the destination catalog."""


AIDP_RUNTIME_PARAMS = frozenset({
    "api_key", "server_url", "tenant_id", "observer",
    "allowed_kds_set", "kds_name_to_id_map",
})


def portable_tool_params(class_name, params):
    """Copy parameters, dropping only platform-managed AIDP runtime fields."""
    return {
        name: deepcopy(value)
        for name, value in (params or {}).items()
        if class_name != "AidpSearchTool" or name not in AIDP_RUNTIME_PARAMS
    }


def validate_import_tool_params(class_name, source, params, catalog_tool):
    """Validate portable parameters without modifying the repository snapshot."""
    if catalog_tool is None:
        raise AgentToolImportError(f"Cannot find tool {class_name} in {source}.")
    portable = portable_tool_params(class_name, params)
    allowed = {param["name"] for param in catalog_tool.get("params", [])}
    for name in portable:
        if name not in allowed:
            raise AgentToolImportError(
                f"Parameter {name} in tool {class_name} from {source} cannot be found."
            )
    return portable
