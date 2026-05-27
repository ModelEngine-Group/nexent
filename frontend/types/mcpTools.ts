import {
  FILTER_ALL,
  McpSource,
  type McpContainerStatus,
  type McpHealthStatus,
  type McpServiceStatus,
  type McpTransportType,
} from "@/const/mcpTools";

export type FilterAll = typeof FILTER_ALL;

/** Source-filter for the main service list (all | local | registry | community). */
export type McpSourceFilter = McpSource | FilterAll;
/** Transport-filter for toolbars (all | http | sse | container). */
export type McpTransportFilter = McpTransportType | FilterAll;


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
  transportType: McpTransportType;
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
  source?: McpSource.COMMUNITY;
  transportType: McpTransportType;
  serverUrl: string;
  configJson?: Record<string, unknown>;
  registryJson?: Record<string, unknown>;
  tags?: string[];
}

export interface McpServiceItem {
  mcpId: number;
  containerId?: string;
  containerPort?: number;
  name: string;
  description: string;
  source: McpSource;
  enabled: McpServiceStatus;
  updatedAt: string;
  tags: string[];
  transportType: McpTransportType;
  serverUrl: string;
  version?: string;
  registryJson?: Record<string, unknown>;
  configJson?: Record<string, unknown>;
  tools: string[];
  healthStatus: McpHealthStatus;
  containerStatus?: McpContainerStatus;
  authorizationToken?: string;
  customHeaders?: Record<string, string>;
}

export interface McpTagStat {
  tag: string;
  count: number;
}

export interface AddMcpServicePayload {
  name: string;
  description: string;
  source: McpSource;
  //transport_type: McpTransportType;
  server_url: string;
  tags: string[];
  authorization_token?: string;
  custom_headers?: Record<string, string>;
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
  custom_headers?: Record<string, string>;
}

export interface ToggleMcpServicePayload {
  mcp_id: number;
  enabled: boolean;
}

export interface HealthcheckMcpServicePayload {
  mcp_id: number;
}

/** One MCP server entry under `mcpServers` for container-based add-from-config. */
export interface McpContainerServerEntry {
  command: string;
  args: string[];
  env?: Record<string, string>;
}

/** Root JSON shape for container add-from-config (`parseContainerMcpConfigJson`). */
export interface McpContainerConfigPayload {
  mcpServers: Record<string, McpContainerServerEntry>;
}

// ---------------------------------------------------------------------------
// Feature-local draft interfaces
// ---------------------------------------------------------------------------

/**
 * Form state owned by the local-add section. Components manage this directly;
 * the shared shape makes it easy to pass the whole draft into a submit helper.
 */
export interface LocalAddMcpDraft {
  name: string;
  description?: string;
  transportType: McpTransportType;
  serverUrl: string;
  authorizationToken?: string;
  customHeaders?: string;
  containerConfigJson: string;
  containerPort?: number;
  tags: string[];
}

/**
 * Form state for the community quick-add confirmation modal.
 */
export interface CommunityQuickAddDraft {
  name: string;
  description?: string;
  transportType: McpTransportType;
  serverUrl: string;
  authorizationToken?: string;
  customHeaders?: string;
  containerConfigJson?: string;
  containerPort?: number;
  tags: string[];
  version?: string;
  registryJson?: Record<string, unknown>;
}
