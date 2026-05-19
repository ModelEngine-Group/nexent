import type { ModalProps } from "antd";

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

/** Main MCP tools page: imported workspace services vs. published community list. */
export enum McpToolsServicesTab {
  IMPORTED = "imported",
  PUBLISHED = "published",
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

/** Add MCP modal width when the local (custom) tab is active. */
export const MCP_ADD_SERVICE_MODAL_WIDTH_LOCAL = 560;

/** Add MCP modal width for registry / community browser tabs. */
export const MCP_ADD_SERVICE_MODAL_WIDTH_MARKETS = 1100;

/** Fixed content column width for the local add-MCP form (matches local tab modal). */
export const MCP_ADD_SERVICE_LOCAL_SECTION_WIDTH_PX = 560;

/** Modal `wrapClassName`: whole dialog scrolls; clears Ant Design max-height on content. */
export const MCP_TOOLS_MODAL_WRAP_CLASS =
  "max-h-[100dvh] overflow-y-auto overflow-x-hidden py-6 [&_.ant-modal]:max-h-none [&_.ant-modal-content]:max-h-none";

export const MCP_TOOLS_MODAL_MASK_STYLE = {
  background: "rgba(15,23,42,0.55)",
  backdropFilter: "blur(3px)",
} as const;

export const MCP_TOOLS_MODAL_BODY_CHROME = {
  padding: 0,
  maxHeight: "none",
  overflow: "visible",
  height: "100%",
  overflowY: "auto",
} as const;

export const MCP_TOOLS_MODAL_BODY_SCROLL_UNLOCK = {
  maxHeight: "none",
  overflow: "visible",
} as const;

export function mcpToolsModalChromeStyles(): NonNullable<ModalProps["styles"]> {
  return {
    mask: { ...MCP_TOOLS_MODAL_MASK_STYLE },
    body: { ...MCP_TOOLS_MODAL_BODY_CHROME },
  };
}

/** Inline height for MCP grid cards (avoids Tailwind scanning `frontend/const/`). */
export const MCP_GRID_CARD_OUTER_STYLE = {
  height: "12rem",
};

/** Layout and chrome for MCP grid cards; pair with `MCP_GRID_CARD_OUTER_STYLE` for height. */
export const MCP_GRID_CARD_OUTER =
  "group flex w-full shrink-0 cursor-pointer flex-col overflow-hidden rounded-md border border-slate-200 bg-white p-4 shadow-sm transition hover:shadow-md";

/**
 * Shared React Query cache keys for the MCP tools feature. Centralised so every
 * hook touching the same data invalidates the same slot.
 */
export const MCP_TOOLS_QUERY_KEYS = {
  services: ["mcp-tools", "services"] as const,
  tools: (mcpId: number) => ["mcp-tools", "service-tools", mcpId] as const,
  registryList: ["mcp-tools", "registry"] as const,
  communityList: ["mcp-tools", "community"] as const,
  communityTags: ["mcp-tools", "community-tags"] as const,
  myCommunity: ["mcp-tools", "my-community"] as const,
};
