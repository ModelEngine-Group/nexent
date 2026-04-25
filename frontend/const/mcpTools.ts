import {
  McpContainerStatus,
  McpHealthStatus,
  McpTransportType,
  McpServiceStatus,
  McpTab,
  McpRegistryServerStatus,
  FILTER_ALL,
} from "@/types/mcpTools";
import type { LocalAddMcpDraft } from "@/types/mcpTools";

export const MCP_TAB = {
  LOCAL: McpTab.LOCAL,
  MCP_REGISTRY: McpTab.MCP_REGISTRY,
  COMMUNITY: McpTab.COMMUNITY,
} as const;

export const MCP_TRANSPORT_TYPE = {
  HTTP: McpTransportType.HTTP,
  SSE: McpTransportType.SSE,
  CONTAINER: McpTransportType.CONTAINER,
} as const;

export const MCP_SERVICE_STATUS = {
  ENABLED: McpServiceStatus.ENABLED,
  DISABLED: McpServiceStatus.DISABLED,
} as const;

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

export const MCP_REGISTRY_SERVER_STATUS = {
  ACTIVE: McpRegistryServerStatus.ACTIVE,
  DEPRECATED: McpRegistryServerStatus.DEPRECATED,
  UNKNOWN: McpRegistryServerStatus.UNKNOWN,
} as const;

/** Field length limits shared by every MCP form (used by rule builders). */
export const MCP_FIELD_LIMITS = {
  NAME: 100,
  DESCRIPTION: 5000,
  URL: 500,
  AUTH_TOKEN: 500,
  QUICK_ADD_FIELD: 2000,
  VERSION: 100,
} as const;

/** Valid range for a container port (TCP). */
export const MCP_PORT_RANGE = { MIN: 1, MAX: 65535 } as const;

/** Debounce for all text-filter inputs on MCP browsers. */
export const MCP_SEARCH_DEBOUNCE_MS = 350;

/** Default blank state for the local-add form. */
export const INITIAL_LOCAL_ADD_DRAFT: LocalAddMcpDraft = {
  name: "",
  description: "",
  transportType: McpTransportType.HTTP,
  serverUrl: "",
  authorizationToken: "",
  containerConfigJson: "",
  containerPort: undefined,
  tags: [],
};

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

/** Semver `x.y.z` required by the registry toolbar custom-version input. */
export const VERSION_PATTERN = /^\d+\.\d+\.\d+$/;

/** Short semver used by the "My community MCP" edit form (`x`, `x.y`, `x.y.z`). */
export const SHORT_VERSION_PATTERN = /^\d+(?:\.\d+){0,2}$/;

export { FILTER_ALL };
