export enum McpTab {
  LOCAL = "local",
  MCP_REGISTRY = "mcp_registry",
  COMMUNITY = "community",
}

export enum McpTransportType {
  HTTP = "http",
  SSE = "sse",
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

/** Sentinel value used by toolbar `Select`s to mean "no filter applied". */
export const FILTER_ALL = "all";
export type FilterAll = typeof FILTER_ALL;

/** Source-filter for the main service list (all | local | registry | community). */
export type McpSourceFilter = McpTab | FilterAll;
/** Transport-filter for toolbars (all | http | sse | container). */
export type McpTransportFilter = McpTransportType | FilterAll;

/** Version-selection modes of the registry toolbar. */
export enum McpVersionFilterMode {
  ALL = "all",
  LATEST = "latest",
  CUSTOM = "custom",
}

/** Server status reported by the MCP registry / community entries. */
export enum McpServerStatus {
  ACTIVE = "active",
  DEPRECATED = "deprecated",
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

export interface RegistryPackageArgumentInput {
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
  transportType: "http" | "sse" | "container";
  serverUrl?: string;
  remoteVariables?: RegistryRemoteVariable[];
  remoteHeaders?: RegistryRemoteVariable[];
  unsupportedRequiredHeaders?: string[];
  packageRuntimeHint?: string;
  packageEnvironmentVariables?: RegistryRemoteVariable[];
  packageTransportHeaders?: RegistryRemoteVariable[];
  packageTransportVariables?: RegistryRemoteVariable[];
  packageRuntimeArguments?: RegistryPackageArgumentInput[];
  packageArguments?: RegistryPackageArgumentInput[];
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
  createdAt: string;
  updatedAt?: string;
  remotes: Array<{ type: string; url: string }>;
  packages: Array<Record<string, unknown>>;
  source?: "community";
  transportType: "http" | "sse" | "container";
  serverUrl: string;
  configJson?: Record<string, unknown> | null;
  registryJson?: Record<string, unknown> | null;
  tags?: string[];
}

export interface McpServiceItem {
  mcpId: number;
  containerId?: string;
  containerPort?: number | null;
  name: string;
  description: string;
  source: McpTab;
  status: McpServiceStatus;
  updatedAt: string;
  tags: string[];
  transportType: McpTransportType;
  serverUrl: string;
  version?: string | null;
  registryJson?: Record<string, unknown> | null;
  configJson?: Record<string, unknown> | null;
  tools: string[];
  healthStatus: McpHealthStatus;
  containerStatus?: McpContainerStatus;
  authorizationToken?: string;
}

export interface McpServerListItem {
  service_name: string;
  mcp_url: string;
  status: boolean;
  permission: string;
  mcp_id: number;
  container_id?: string | null;
  description?: string;
  enabled?: boolean;
  source?: string;
  update_time?: string;
  tags?: string[];
  container_port?: number | null;
  registry_json?: Record<string, unknown> | null;
  config_json?: Record<string, unknown> | null;
  health_status?: McpHealthStatus;
  container_status?: McpContainerStatus;
  authorization_token?: string;
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

// ---------------------------------------------------------------------------
// Feature-local draft interfaces (kept here so components/hooks share shape)
// ---------------------------------------------------------------------------

/**
 * Form state owned by the local-add section. Components manage this directly;
 * the shared shape makes it easy to pass the whole draft into a submit helper.
 */
export interface LocalAddMcpDraft {
  name: string;
  description: string;
  transportType: McpTransportType;
  serverUrl: string;
  authorizationToken: string;
  containerConfigJson: string;
  containerPort: number | undefined;
  tags: string[];
}

/**
 * Form state for the community quick-add confirmation modal.
 */
export interface CommunityQuickAddDraft {
  name: string;
  description: string;
  transportType: McpTransportType;
  serverUrl: string;
  authorizationToken: string;
  containerConfigJson: string;
  containerPort: number | undefined;
  tags: string[];
  version?: string;
  registryJson?: Record<string, unknown>;
}
