export enum McpSource {
  LOCAL = "local",
  REGISTRY = "mcp_registry",
  COMMUNITY = "community",
}

export enum McpTransportType {
  HTTP = "http",
  SSE = "sse",
  URL = "url",
  CONTAINER = "container",
}

export enum McpServiceStatus {
  ENABLED = "enabled",
  DISABLED = "disabled",
}

export enum McpHealthStatus {
  HEALTHY = "healthy",
  UNHEALTHY = "unhealthy",
  UNCHECKED = "unchecked",
}

export enum McpContainerStatus {
  RUNNING = "running",
  STOPPED = "stopped",
  UNKNOWN = "unknown",
}

export enum McpVersionFilterMode {
  ALL = "all",
  LATEST = "latest",
  CUSTOM = "custom",
}

export enum McpServerStatus {
  ACTIVE = "active",
  DEPRECATED = "deprecated",
  UNKNOWN = "unknown",
}

/** Sentinel value used by toolbar `Select`s to mean "no filter applied". */
export const FILTER_ALL = "all";

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

export const MCP_GRID_CARD_OUTER =
  "group flex h-56 w-full min-h-56 max-h-56 shrink-0 cursor-pointer flex-col overflow-hidden rounded-md border border-slate-200 bg-white p-4 shadow-sm transition hover:shadow-md";

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
