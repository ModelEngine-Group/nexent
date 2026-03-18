import type { UploadFile } from "antd/es/upload/interface";
import type { McpTool } from "@/types/agentConfig";

export enum McpTab {
  LOCAL = "local",
  MARKET = "market",
}

export enum McpServerType {
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

export interface MarketMcpCard {
  name: string;
  title: string;
  version: string;
  description: string;
  publishedAt: string;
  status: string;
  websiteUrl: string;
  remotes: Array<{ type: string; url: string }>;
  serverJson: Record<string, unknown>;
  serverType: McpServerType;
  serverUrl: string;
}

export interface AddMcpLocalState {
  newServiceName: string;
  newServiceDesc: string;
  newServerType: McpServerType;
  newServiceUrl: string;
  newServiceAuthorizationToken: string;
  containerUploadFileList: UploadFile[];
  containerConfigJson: string;
  containerPort: number | undefined;
  containerServiceName: string;
  newTagDrafts: string[];
  newTagInputValue: string;
  addingService: boolean;
}

export interface AddMcpMarketState {
  marketSearchValue: string;
  selectedMarketService: MarketMcpCard | null;
  filteredMarketServices: MarketMcpCard[];
  marketLoading: boolean;
  marketPage: number;
  hasPrevMarketPage: boolean;
  hasNextMarketPage: boolean;
  marketVersion: string;
  marketUpdatedSince: string;
  marketIncludeDeleted: boolean;
}

export interface AddMcpLocalActions {
  onNewServiceNameChange: (value: string) => void;
  onNewServiceDescChange: (value: string) => void;
  onNewServerTypeChange: (value: McpServerType) => void;
  onNewServiceUrlChange: (value: string) => void;
  onNewServiceAuthorizationTokenChange: (value: string) => void;
  onContainerUploadFileListChange: (fileList: UploadFile[]) => void;
  onContainerConfigJsonChange: (value: string) => void;
  onContainerPortChange: (value: number | undefined) => void;
  onContainerServiceNameChange: (value: string) => void;
  onAddNewTag: () => void;
  onRemoveNewTag: (index: number) => void;
  onNewTagInputChange: (value: string) => void;
  onSaveAndAdd: () => void;
}

export interface AddMcpMarketActions {
  onMarketSearchChange: (value: string) => void;
  onRefreshMarket: () => void;
  onPrevMarketPage: () => void;
  onNextMarketPage: () => void;
  onMarketVersionChange: (value: string) => void;
  onMarketUpdatedSinceChange: (value: string) => void;
  onMarketIncludeDeletedChange: (value: boolean) => void;
  onSelectMarketService: (service: MarketMcpCard | null) => void;
  onQuickAddFromMarket: (service: MarketMcpCard) => void;
}

export interface McpServiceDetailState {
  selectedService: McpServiceItem | null;
  draftService: McpServiceItem | null;
  tagDrafts: string[];
  tagInputValue: string;
  healthCheckLoading: boolean;
  loadingTools: boolean;
  toolsModalVisible: boolean;
  currentServerTools: McpTool[];
}

export interface McpServiceDetailActions {
  onDraftServiceChange: (service: McpServiceItem) => void;
  onTagInputChange: (value: string) => void;
  onAddDetailTag: () => void;
  onRemoveTag: (index: number) => void;
  onHealthCheck: () => void;
  onViewTools: () => void;
  onSaveUpdates: () => void;
  onCloseToolsModal: () => void;
  onRefreshTools: () => void;
}

export interface McpServiceItem {
  name: string;
  description: string;
  source: McpTab;
  status: McpServiceStatus;
  updatedAt: string;
  tags: string[];
  serverType: McpServerType;
  serverUrl: string;
  tools: string[];
  healthStatus: McpHealthStatus;
  containerStatus?: McpContainerStatus;
  authorizationToken?: string;
}

export interface AddMcpServicePayload {
  name: string;
  description: string;
  source: McpTab;
  server_type: McpServerType;
  server_url: string;
  tags: string[];
  authorization_token?: string;
  container_config?: Record<string, unknown>;
}

export interface UpdateMcpServicePayload {
  current_name: string;
  name: string;
  description: string;
  server_url: string;
  tags: string[];
  authorization_token?: string;
}

export interface ToggleMcpServicePayload {
  name: string;
  enabled: boolean;
}

export interface HealthcheckMcpServicePayload {
  name: string;
  server_url: string;
}

export interface AddMcpRuntimeServerPayload {
  port?: number;
  [key: string]: unknown;
}

export interface AddMcpRuntimeFromConfigPayload {
  mcpServers: Record<string, AddMcpRuntimeServerPayload>;
}

