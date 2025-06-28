from fastmcp import FastMCP, Client
from starlette.requests import Request
from starlette.responses import JSONResponse
from mcp_service.local_mcp_service import local_mcp_service
from mcp_service.common_function import RemoteMCPConfig, validate_url_params
from mcp_service.remote_mcp_service_manager import RemoteProxyManager

"""
hierarchical proxy architecture:
- local service layer: stable local mount service
- remote proxy layer: dynamic managed remote mcp service proxy
"""

# initialize main mcp service
nexent_mcp = FastMCP(name="nexent_mcp")

# mount local service (stable, not affected by remote proxy)
nexent_mcp.mount(local_mcp_service.name, local_mcp_service)

# initialize remote proxy manager
proxy_manager = RemoteProxyManager(nexent_mcp)


@nexent_mcp.custom_route("/healthcheck", methods=["GET"])
async def healthcheck(request: Request):
    """healthcheck endpoint - focus on verifying connection availability"""
    # validate params
    is_valid, result = validate_url_params(request, required_query_params=["mcp_url"])
    if not is_valid:
        return result
    
    mcp_url = result["mcp_url"]
    
    try:
        # only verify remote mcp service connection
        client = Client(mcp_url)
        async with client:
            # simple connection test, no detailed information
            connected = client.is_connected()
            return JSONResponse({
                "status": "success",
                "message": "MCP service is reachable",
                "connected": connected,
                "url": mcp_url
            })
    except Exception as e:
        return JSONResponse({
            "status": "error", 
            "message": f"Failed to connect to MCP server: {e}",
            "url": mcp_url
        }, status_code=500)


@nexent_mcp.custom_route("/list-remote-proxies", methods=["GET"])
async def list_remote_proxies(request: Request):
    """list all remote proxy configs"""
    proxies = proxy_manager.list_remote_proxies()
    return JSONResponse({
        "status": "success",
        "proxies": {name: {"mcp_url": config.mcp_url, "transport": config.transport}
                   for name, config in proxies.items()}
    })


@nexent_mcp.custom_route("/add-remote-proxies", methods=["POST"])
async def add_remote_proxy(request: Request):
    """add remote proxy service"""
    try:
        body = await request.json()
        req_data = RemoteMCPConfig(**body)
        try:
            config = RemoteMCPConfig(
                mcp_url=req_data.mcp_url,
                service_name=req_data.service_name,
                transport=req_data.transport
            )
        except Exception as e:
            return JSONResponse({
                "status": "error",
                "message": f"Invalid request: {e}"
            }, status_code=400)

        success = await proxy_manager.add_remote_proxy(config)

        if success:
            return JSONResponse({
                "status": "success",
                "message": f"Remote proxy '{req_data.service_name}' added successfully"
            })
        else:
            return JSONResponse({
                "status": "error",
                "message": f"Failed to add remote proxy '{req_data.service_name}'"
            }, status_code=500)
    except ValueError:
        return JSONResponse({
            "status": "error",
            "message": "Service name already exists"
        }, status_code=409)
    except ConnectionError:
        return JSONResponse({
            "status": "error",
            "message": "Cannot connect to remote MCP server"
        }, status_code=503)
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": f"Invalid request: {e}"
        }, status_code=400)


@nexent_mcp.custom_route("/remote-proxies", methods=["DELETE"])
async def remove_remote_proxy(request: Request):
    """remove remote proxy service"""
    try:
        # validate params
        is_valid, result = validate_url_params(request, required_query_params=["service_name"])
        if not is_valid:
            return result
        
        service_name = result["service_name"]
        
        success = await proxy_manager.remove_remote_proxy(service_name)
        
        if success:
            return JSONResponse({
                "status": "success",
                "message": f"Remote proxy '{service_name}' removed successfully"
            })
        else:
            return JSONResponse({
                "status": "error",
                "message": f"Remote proxy '{service_name}' not found"
            }, status_code=404)
            
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": f"Failed to remove remote proxy: {e}"
        }, status_code=500)


if __name__ == "__main__":
    nexent_mcp.run(transport="sse", port=5011)
