import type { McpTool } from "@/types/agentConfig";

export enum McpTab {
  LOCAL = "local",
  MCP_REGISTRY = "mcp_registry",
}

export enum McpTransportType {
  HTTP = "http",
  SSE = "sse",
  STDIO = "stdio",
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

export interface RegistryMcpCard {
  name: string;
  version: string;
  description: string;
  publishedAt: string;
  status: string;
  remotes: Array<{ type: string; url: string }>;
  packages: Array<{
    registryType: string;
    identifier: string;
    version: string;
    runtimeHint: string;
    transport: { type: string; url: string };
  }>;
  serverJson: Record<string, unknown>;
}

export interface RegistryQuickAddOption {
  key: string;
  sourceType: "remote" | "package";
  sourceLabel: string;
  transportType: "http" | "sse" | "stdio";
  serverUrl?: string;
  packageIdentifier?: string;
  packageRegistryType?: string;
  packageEnvTemplate?: Record<string, string>;
}

export interface McpServiceItem {
  mcpId: number;
  containerId?: string;
  name: string;
  description: string;
  source: McpTab;
  status: McpServiceStatus;
  updatedAt: string;
  tags: string[];
  transportType: McpTransportType;
  serverUrl: string;
  version?: string | null;
  mcpRegistryJson?: Record<string, unknown> | null;
  configJson?: Record<string, unknown> | null;
  tools: string[];
  healthStatus: McpHealthStatus;
  containerStatus?: McpContainerStatus;
  authorizationToken?: string;
}

export interface AddMcpServicePayload {
  name: string;
  description: string;
  source: McpTab;
  transport_type: McpTransportType;
  server_url: string;
  tags: string[];
  authorization_token?: string;
  container_config?: Record<string, unknown>;
  version?: string;
  registry_json?: Record<string, unknown>;
}

export interface UpdateMcpServicePayload {
  mcp_id: number;
  name: string;
  description: string;
  server_url: string;
  tags: string[];
  authorization_token?: string;
}

export interface ToggleMcpServicePayload {
  mcp_id: number;
  enabled: boolean;
}

export interface HealthcheckMcpServicePayload {
  mcp_id: number;
}

export interface AddMcpRuntimeServerPayload {
  port?: number;
  [key: string]: unknown;
}

export interface AddMcpRuntimeFromConfigPayload {
  mcpServers: Record<string, AddMcpRuntimeServerPayload>;
}

