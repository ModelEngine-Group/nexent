import {
	McpContainerStatus,
	McpHealthStatus,
	McpTransportType,
	McpServiceStatus,
	McpTab,
} from "@/types/mcpTools";

export const MCP_TAB = { LOCAL: McpTab.LOCAL, MCP_REGISTRY: McpTab.MCP_REGISTRY, COMMUNITY: McpTab.COMMUNITY } as const;
export const MCP_TRANSPORT_TYPE = { HTTP: McpTransportType.HTTP, SSE: McpTransportType.SSE, CONTAINER: McpTransportType.CONTAINER } as const;
export const MCP_SERVICE_STATUS = { ENABLED: McpServiceStatus.ENABLED, DISABLED: McpServiceStatus.DISABLED } as const;
export const MCP_HEALTH_STATUS = {
	HEALTHY: McpHealthStatus.HEALTHY,
	UNHEALTHY: McpHealthStatus.UNHEALTHY,
	UNCHECKED: McpHealthStatus.UNCHECKED,
} as const;
export const MCP_CONTAINER_STATUS = {
	RUNNING: McpContainerStatus.RUNNING,
	STOPPED: McpContainerStatus.STOPPED,
	UNKNOWN: McpContainerStatus.UNKNOWN,
} as const;

export const MCP_REGISTRY_SERVER_STATUS = { ACTIVE: "active", DEPRECATED: "deprecated", UNKNOWN: "unknown" } as const;

/**
 * Shared React Query cache keys for the MCP tools feature. Centralised so every
 * hook touching the same data invalidates the same slot.
 */
export const MCP_TOOLS_QUERY_KEYS = {
  services: ["mcp-tools", "services"] as const,
  tagStats: ["mcp-tools", "tag-stats"] as const,
  tools: (mcpId: number) => ["mcp-tools", "service-tools", mcpId] as const,
  registryList: ["mcp-tools", "registry"] as const,
  communityList: ["mcp-tools", "community"] as const,
  communityTags: ["mcp-tools", "community-tags"] as const,
  myCommunity: ["mcp-tools", "my-community"] as const,
};
export const MCP_TOOLS_INVALIDATION_KEYS = [
  MCP_TOOLS_QUERY_KEYS.services,
  MCP_TOOLS_QUERY_KEYS.tagStats,
] as const;

export const VERSION_PATTERN = /^\d+\.\d+\.\d+$/;