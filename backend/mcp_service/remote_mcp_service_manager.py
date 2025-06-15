from typing import Dict
from fastmcp import FastMCP, Client
from mcp_service.common_function import (RemoteMCPConfig, create_proxy_config)


class RemoteProxyManager:
    """remote mcp service proxy manager"""

    def __init__(self, nexent_mcp: FastMCP):
        self.nexent_mcp = nexent_mcp
        self.remote_proxies: Dict[str, FastMCP] = {}
        self.remote_configs: Dict[str, RemoteMCPConfig] = {}

    async def add_remote_proxy(self, config: RemoteMCPConfig) -> bool:
        """add remote proxy service"""
        try:
            # validate connection
            await self._validate_remote_service(config.mcp_url)

            # create proxy config
            proxy_config = create_proxy_config([config])

            # create proxy service
            proxy_service = FastMCP.as_proxy(proxy_config, name=f"remote_{config.service_name}")

            # if service name already exists, raise exception
            if config.service_name in self.remote_proxies:
                raise ValueError(f"Service {config.service_name} already exists")

            # mount new service
            self.nexent_mcp.mount(f"remote_{config.service_name}", proxy_service)

            # save reference
            self.remote_proxies[config.service_name] = proxy_service
            self.remote_configs[config.service_name] = config

            return True
        except Exception as e:
            print(f"Failed to add remote proxy {config.service_name}: {e}")
            return False

    async def remove_remote_proxy(self, service_name: str) -> bool:
        """remove remote proxy service"""
        try:
            if service_name in self.remote_proxies:
                # unmount service
                self.nexent_mcp.unmount(f"remote_{service_name}")

                # clean reference
                del self.remote_proxies[service_name]
                del self.remote_configs[service_name]

                return True
            return False
        except Exception as e:
            print(f"Failed to remove remote proxy {service_name}: {e}")
            return False

    def list_remote_proxies(self) -> Dict[str, RemoteMCPConfig]:
        """list all remote proxy configs"""
        return self.remote_configs.copy()

    async def _validate_remote_service(self, mcp_url: str) -> bool:
        """validate remote mcp service connection"""
        client = Client(mcp_url)
        try:
            async with client:
                await client.list_tools()
                return True
        except Exception as e:
            raise Exception(f"Failed to connect to MCP server: {e}")
