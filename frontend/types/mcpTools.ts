import type { McpTool } from "@/types/agentConfig";

export enum McpTab {
  LOCAL = "local",
  MCP_REGISTRY = "mcp_registry",
  COMMUNITY = "community",
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

export interface RegistryServerPayload {
  name: string;
  version?: string;
  description?: string;
  websiteUrl?: string;
  repository?: {
    url?: string;
    source?: string;
    id?: string;
  };
  remotes: Array<{
    type: string;
    url: string;
    variables?: Record<string, unknown>;
    headers?: Array<{
      name?: string;
      description?: string;
      isRequired?: boolean;
      isSecret?: boolean;
      format?: string;
      value?: string;
      default?: string;
      placeholder?: string;
      choices?: string[];
      variables?: Record<string, unknown>;
      [key: string]: unknown;
    }>;
    [key: string]: unknown;
  }>;
  packages: Array<{
    registryType?: string;
    identifier?: string;
    version?: string;
    runtimeHint?: string;
    transport?: {
      type?: string;
      url?: string;
      headers?: unknown;
      variables?: unknown;
      [key: string]: unknown;
    };
    environmentVariables?: unknown;
    runtimeArguments?: unknown;
    [key: string]: unknown;
  }>;
  [key: string]: unknown;
}

export interface RegistryMcpCard {
  server: RegistryServerPayload;
  _meta?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface RegistryRemoteVariable {
  key: string;
  formKey?: string;
  label?: string;
  description?: string;
  format?: string;
  default?: string;
  placeholder?: string;
  value?: string;
  isRequired?: boolean;
  isSecret?: boolean;
  choices?: string[];
  variables?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface RegistryRuntimeArgumentInput {
  key: string;
  formKey: string;
  label: string;
  type: "named" | "positional";
  name?: string;
  valueHint?: string;
  description?: string;
  format?: string;
  default?: string;
  value?: string;
  isRequired?: boolean;
  isSecret?: boolean;
  isRepeated?: boolean;
}

export interface RegistryQuickAddOption {
  key: string;
  sourceType: "remote" | "package";
  sourceLabel: string;
  transportType: "http" | "sse" | "stdio";
  serverUrl?: string;
  serverUrlTemplate?: string;
  remoteVariables?: RegistryRemoteVariable[];
  packageIndex?: number;
  packageRuntimeHint?: string;
  packageEnvironmentVariables?: RegistryRemoteVariable[];
  packageTransportHeaders?: RegistryRemoteVariable[];
  packageTransportVariables?: RegistryRemoteVariable[];
  packageRuntimeArguments?: RegistryRuntimeArgumentInput[];
  packageIdentifier?: string;
  packageRegistryType?: string;
  packageEnvTemplate?: Record<string, string>;
}

export interface CommunityMcpCard {
  communityId?: number;
  name: string;
  version?: string;
  description: string;
  status: string;
  publishedAt: string;
  updatedAt?: string;
  remotes: Array<{ type: string; url: string }>;
  packages: Array<Record<string, unknown>>;
  serverJson: Record<string, unknown>;
  source?: "community";
  transportType: "http" | "sse" | "stdio";
  serverUrl: string;
  configJson?: Record<string, unknown> | null;
  mcpRegistryJson?: Record<string, unknown> | null;
  tags?: string[];
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

export interface McpTagStat {
  tag: string;
  count: number;
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

