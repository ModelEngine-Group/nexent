import {
	McpContainerStatus,
	McpHealthStatus,
	McpServerType,
	McpServiceStatus,
	McpTab,
} from "@/types/mcpTools";

export const MCP_TAB = { LOCAL: McpTab.LOCAL, MARKET: McpTab.MARKET } as const;
export const MCP_SERVER_TYPE = { HTTP: McpServerType.HTTP, SSE: McpServerType.SSE, CONTAINER: McpServerType.CONTAINER } as const;
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
export const MARKET_SERVER_STATUS = { ACTIVE: "active", DEPRECATED: "deprecated", UNKNOWN: "unknown" } as const;
