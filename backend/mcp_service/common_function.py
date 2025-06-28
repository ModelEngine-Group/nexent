from typing import List
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse


class RemoteMCPConfig(BaseModel):
    mcp_url: str
    service_name: str
    transport: str = Field(default="sse", description="sse or streamable-http")


def create_proxy_config(remote_mcp_config_list: List[RemoteMCPConfig]):
    config = {
        "mcpServers": {
            remote_mcp_config.service_name: {
                "url": remote_mcp_config.mcp_url,
                "transport": remote_mcp_config.transport
            }
            for remote_mcp_config in remote_mcp_config_list
        }
    }
    return config


def validate_url_params(request: Request, required_query_params=None):
    """
    common function for validate url params

    Args:
        request: Starlette Request object
        required_query_params: required query params list

    Returns:
        tuple: (is_valid, error_response_or_params)
        - if valid: (True, {})
        - if invalid: (False, JSONResponse)
    """
    params = {}

    # validate query params
    if required_query_params:
        for param_name in required_query_params:
            param_value = request.query_params.get(param_name)
            if not param_value:
                return False, JSONResponse({
                    "error": f"query param '{param_name}' is required"
                }, status_code=400)
            params[param_name] = param_value

    return True, params