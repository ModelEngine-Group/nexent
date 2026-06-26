import log from "@/lib/logger";
import { fetchWithAuth } from "@/lib/auth";
import {
  McpContainerStatus,
  McpHealthStatus,
  McpServiceStatus,
  McpSource,
  McpTransportType,
} from "@/const/mcpTools";
import { API_ENDPOINTS } from "@/services/api";
import type {
  AddMcpServicePayload,
  HealthcheckMcpServicePayload,
  McpContainerConfigPayload,
  McpContainerServerEntry,
  RegistryMcpCard,
  CommunityMcpCard,
  McpTagStat,
  McpServiceItem,
  ToggleMcpServicePayload,
  UpdateMcpServicePayload,
} from "@/types/mcpTools";
import type { McpTool } from "@/types/agentConfig";

export type McpToolsApiResult<T> = {
  success: boolean;
  data: T;
};

export type { RegistryMcpCard as RegistryMcpCard } from "@/types/mcpTools";

type ApiEnvelope<T = unknown> = {
  status: string;
  message?: string;
  detail?: string;
  data: T;
  tools?: McpTool[];
  results?: Array<{ mcp_url?: string }>;
  mcp_url?: string;
};

type AddContainerMcpToolPayload = {
  name: string;
  description?: string;
  tags: string[];
  source: McpSource;
  authorization_token?: string;
  registry_json?: Record<string, unknown>;
  version?: string;
  market_id?: number;
  port: number;
  mcp_config: McpContainerConfigPayload;
};

type PortConflictResult = {
  available: boolean;
};

const parseJson = async <T = ApiEnvelope>(response: Response): Promise<T> => {
  return (await response.json()) as T;
};

type HealthcheckPayload = {
  health_status: McpHealthStatus;
};

export const fetchRegistryMcpCards = async (params: {
  search?: string;
  cursor?: string | null;
  version?: string;
  updatedSince?: string;
  includeDeleted?: boolean;
  source?: string;
}) => {
  const query = new URLSearchParams();
  query.set("limit", "30");
  if (params.search?.trim()) {
    query.set("search", params.search.trim());
  }
  if (params.version?.trim()) {
    query.set("version", params.version.trim());
  }
  if (params.updatedSince?.trim()) {
    query.set("updated_since", params.updatedSince.trim());
  }
  query.set("include_deleted", params.includeDeleted ? "true" : "false");
  if (params.cursor) {
    query.set("cursor", params.cursor);
  }
  if (params.source) {
    query.set("source", params.source);
  }

  const result = await listRegistryMcpTools(query);
  const payload = result.data;

  return {
    success: true,
    data: {
      items: payload.items,
      nextCursor: payload.nextCursor ?? null,
    },
  } as McpToolsApiResult<{
    items: RegistryMcpCard[];
    nextCursor: string | null;
  }>;
};

export const fetchCommunityMcpCards = async (params: {
  search?: string;
  cursor?: string | null;
  transportType?: McpTransportType;
  tag?: string;
  limit?: number;
}) => {
  const result = await listCommunityMcpTools({
    search: params.search?.trim() || undefined,
    cursor: params.cursor || undefined,
    transport_type: params.transportType,
    tag: params.tag?.trim() || undefined,
    limit: params.limit ?? 30,
  });

  return {
    success: true,
    data: {
      items: result.data.items,
      nextCursor: result.data.nextCursor ?? null,
    },
  } as McpToolsApiResult<{
    items: CommunityMcpCard[];
    nextCursor: string | null;
  }>;
};

export const fetchCommunityMcpTagStats = async () => {
  try {
    const response = await fetchWithAuth(
      API_ENDPOINTS.mcpTools.communityTagsStats
    );
    const data = await parseJson<ApiEnvelope<McpTagStat[]>>(response);
    if (data.status !== "success") {
      throw new Error("Failed to load community MCP tag stats");
    }
    return { success: true, data: data.data } as McpToolsApiResult<
      McpTagStat[]
    >;
  } catch (error) {
    log.error("fetchCommunityMcpTagStats failed", error);
    throw error;
  }
};

export const checkMcpContainerPortConflictService = async (payload: {
  port: number;
}) => {
  try {
    const query = new URLSearchParams();
    query.set("port", payload.port.toString());
    const response = await fetchWithAuth(
      `${API_ENDPOINTS.mcp.portCheck}?${query.toString()}`
    );
    const data = await parseJson<ApiEnvelope<PortConflictResult>>(response);
    if (data.status !== "success") {
      throw new Error("Failed to check MCP port conflict");
    }
    return {
      success: true,
      data: data.data,
    } as McpToolsApiResult<PortConflictResult>;
  } catch (error) {
    log.error("checkMcpContainerPortConflictService failed", error);
    throw error;
  }
};

export const suggestMcpContainerPortService = async () => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcp.portSuggest);
    const data = await parseJson<ApiEnvelope<{ port: number }>>(response);
    if (data.status !== "success") {
      throw new Error("Failed to suggest MCP port");
    }
    return { success: true, data: data.data } as McpToolsApiResult<{
      port: number;
    }>;
  } catch (error) {
    log.error("suggestMcpContainerPortService failed", error);
    throw error;
  }
};

/**
 * Parses and validates container config JSON for add-from-config. Returns a
 * typed payload or null (single `JSON.parse`; no network I/O). Each server
 * entry requires `command` and `args`; `env` is optional when valid.
 */
export function parseContainerMcpConfigJson(
  raw: string
): McpContainerConfigPayload | null {
  const text = raw.trim();
  if (!text) return null;

  let root: unknown;
  try {
    root = JSON.parse(text);
  } catch {
    return null;
  }

  if (!root || typeof root !== "object" || Array.isArray(root)) return null;
  const rk = Object.keys(root);
  if (rk.length !== 1 || rk[0] !== "mcpServers") return null;

  const ms = (root as { mcpServers: unknown }).mcpServers;
  if (!ms || typeof ms !== "object" || Array.isArray(ms)) return null;

  const names = Object.keys(ms);
  if (names.length !== 1) return null;

  const entry = (ms as Record<string, unknown>)[names[0]!];
  if (!entry || typeof entry !== "object" || Array.isArray(entry)) return null;

  const entryObj = entry as Record<string, unknown>;
  const keys = Object.keys(entryObj);
  const allow = new Set(["command", "args", "env"]);
  if (!keys.every((k) => allow.has(k))) return null;
  if (!keys.includes("command") || !keys.includes("args")) return null;

  const command = entryObj.command;
  const args = entryObj.args;
  if (typeof command !== "string" || !command.trim()) return null;
  if (!Array.isArray(args) || !args.every((a) => typeof a === "string"))
    return null;

  const server: McpContainerServerEntry = {
    command: command.trim(),
    args: args as string[],
  };

  if ("env" in entryObj) {
    const envRaw = entryObj.env;
    if (envRaw === null) return null;
    if (typeof envRaw !== "object" || Array.isArray(envRaw)) return null;
    const envOut: Record<string, string> = {};
    for (const [k, v] of Object.entries(envRaw as Record<string, unknown>)) {
      if (typeof k !== "string" || typeof v !== "string") return null;
      envOut[k] = v;
    }
    server.env = envOut;
  }

  return {
    mcpServers: {
      [names[0]]: server,
    },
  };
}

export const addContainerMcpToolService = async (
  payload: AddContainerMcpToolPayload
) => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcp.addFromConfig, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const data = await parseJson<ApiEnvelope>(response);
    if (data.status !== "success") {
      throw new Error("Failed to add container MCP service");
    }
    return { success: true, data: data.data } as McpToolsApiResult<unknown>;
  } catch (error) {
    log.error("addContainerMcpToolService failed", error);
    throw error;
  }
};

export const listMcpTools = async (params?: { tag?: string }) => {
  const { getMcpServerList } = await import("./mcpService");
  const res = await getMcpServerList();

  const items = (res.data || []).map((s: any) => {
    return {
      mcpId: s.mcp_id,
      containerId: s.container_id,
      containerPort: s.container_port ?? undefined,
      name: s.service_name,
      description: s.description,
      source: s.source as McpSource,
      enabled: s.enabled ? McpServiceStatus.ENABLED : McpServiceStatus.DISABLED,
      updatedAt: s.update_time,
      tags: s.tags || [],
      transportType:
        (s.config_json !== undefined && s.config_json !== null) ||
        (s.container_id !== undefined && s.container_id !== null) ||
        (s.container_port !== undefined && s.container_port !== null)
          ? McpTransportType.CONTAINER
          : McpTransportType.URL,
      serverUrl: s.mcp_url,
      version: s.version ?? undefined,
      registryJson: s.registry_json ?? undefined,
      configJson: s.config_json ?? undefined,
      tools: [],
      healthStatus: s.status
        ? McpHealthStatus.HEALTHY
        : McpHealthStatus.UNCHECKED,
      containerStatus: s.container_status as McpContainerStatus,
      authorizationToken: s.authorization_token,
      customHeaders: s.custom_headers ?? undefined,
      communityId: s.market_id ?? undefined,
      isListedInRepository: s.is_listed_in_repository ?? undefined,
      permission: s.permission ?? undefined,
    } as McpServiceItem;
  });
  return { success: true, data: items } as McpToolsApiResult<McpServiceItem[]>;
};

export const listRegistryMcpTools = async (query: URLSearchParams) => {
  try {
    const response = await fetchWithAuth(
      `${API_ENDPOINTS.mcpTools.registryList}?${query.toString()}`
    );
    const data = await parseJson<{
      servers?: RegistryMcpCard[];
      metadata?: { nextCursor?: string | null };
    }>(response);
    if (!data || !Array.isArray(data.servers)) {
      throw new Error("Failed to load registry mcp list");
    }
    return {
      success: true,
      data: {
        items: data.servers,
        nextCursor: data.metadata?.nextCursor ?? null,
      },
    } as McpToolsApiResult<{
      items: RegistryMcpCard[];
      nextCursor: string | null;
    }>;
  } catch (error) {
    log.error("listRegistryMcpTools failed", error);
    throw error;
  }
};

export const fetchRegistryServerDetail = async (
  source: string,
  qualifiedName: string
): Promise<RegistryMcpCard | null> => {
  try {
    const query = new URLSearchParams();
    query.set("source", source);
    query.set("qualified_name", qualifiedName);
    const response = await fetchWithAuth(
      `${API_ENDPOINTS.mcpTools.registryServerDetail}?${query.toString()}`
    );
    const data = await parseJson<{
      servers?: RegistryMcpCard[];
    }>(response);
    if (data?.servers?.length) {
      return data.servers[0];
    }
    return null;
  } catch (error) {
    log.error("fetchRegistryServerDetail failed", error);
    return null;
  }
};

type CommunityMcpListPayload = {
  search?: string;
  tag?: string;
  transport_type?: McpTransportType;
  cursor?: string;
  limit?: number;
};

type CommunityMcpReviewListPayload = CommunityMcpListPayload & {
  status?: string;
};

export const listCommunityMcpTools = async (payload: CommunityMcpListPayload) => {
  try {
    const response = await fetchWithAuth(
      buildCommunityMcpListUrl(API_ENDPOINTS.mcpTools.communityList, payload)
    );
    const data =
      await parseJson<
        ApiEnvelope<{ items: CommunityMcpCard[]; nextCursor: string | null }>
      >(response);
    if (data.status !== "success") {
      throw new Error("Failed to load community mcp list");
    }
    return { success: true, data: data.data } as McpToolsApiResult<{
      items: CommunityMcpCard[];
      nextCursor: string | null;
    }>;
  } catch (error) {
    log.error("listCommunityMcpTools failed", error);
    throw error;
  }
};

export const listCommunityMcpReviewTools = async (
  payload: CommunityMcpReviewListPayload
) => {
  try {
    const response = await fetchWithAuth(
      buildCommunityMcpListUrl(API_ENDPOINTS.mcpTools.communityReviewList, payload)
    );
    const data =
      await parseJson<
        ApiEnvelope<{ items: CommunityMcpCard[]; nextCursor: string | null }>
      >(response);
    if (data.status !== "success") {
      throw new Error("Failed to load community mcp review list");
    }
    return { success: true, data: data.data } as McpToolsApiResult<{
      items: CommunityMcpCard[];
      nextCursor: string | null;
    }>;
  } catch (error) {
    log.error("listCommunityMcpReviewTools failed", error);
    throw error;
  }
};

const buildCommunityMcpListUrl = (
  endpoint: string,
  payload: CommunityMcpReviewListPayload
) => {
  const query = new URLSearchParams();
  if (payload.search) query.set("search", payload.search);
  if (payload.tag) query.set("tag", payload.tag);
  if (payload.transport_type)
    query.set("transport_type", payload.transport_type.toString());
  if (payload.status) query.set("status", payload.status);
  if (payload.cursor) query.set("cursor", payload.cursor);
  if (typeof payload.limit === "number") query.set("limit", String(payload.limit));

  const queryString = query.toString();
  return queryString ? `${endpoint}?${queryString}` : endpoint;
};

export const approveCommunityMcpTool = async (reviewId: number) => {
  try {
    const response = await fetchWithAuth(
      API_ENDPOINTS.mcpTools.communityReviewApprove,
      {
        method: "POST",
        body: JSON.stringify({ review_id: reviewId }),
      }
    );
    const data = await parseJson<ApiEnvelope>(response);
    if (data.status !== "success") {
      throw new Error("Failed to approve community mcp");
    }
    return { success: true, data: null } as McpToolsApiResult<null>;
  } catch (error) {
    log.error("approveCommunityMcpTool failed", error);
    throw error;
  }
};

export const rejectCommunityMcpTool = async (reviewId: number) => {
  try {
    const response = await fetchWithAuth(
      API_ENDPOINTS.mcpTools.communityReviewReject,
      {
        method: "POST",
        body: JSON.stringify({ review_id: reviewId }),
      }
    );
    const data = await parseJson<ApiEnvelope>(response);
    if (data.status !== "success") {
      throw new Error("Failed to reject community mcp");
    }
    return { success: true, data: null } as McpToolsApiResult<null>;
  } catch (error) {
    log.error("rejectCommunityMcpTool failed", error);
    throw error;
  }
};

/** Body for POST /mcp-tools/community/publish (optional fields override the local MCP snapshot). */
export type PublishCommunityMcpToolPayload = {
  mcp_id: number;
  name?: string;
  description?: string;
  version?: string;
  tags?: string[];
  mcp_server?: string;
  config_json?: McpContainerConfigPayload;
};

export const publishCommunityMcpTool = async (
  payload: PublishCommunityMcpToolPayload
) => {
  try {
    const response = await fetchWithAuth(
      API_ENDPOINTS.mcpTools.communityPublish,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
    const data =
      await parseJson<ApiEnvelope<{ review_id: number }>>(response);
    if (data.status !== "success") {
      throw new Error("Failed to publish community mcp");
    }
    return { success: true, data: data.data } as McpToolsApiResult<{
      review_id: number;
    }>;
  } catch (error) {
    log.error("publishCommunityMcpTool failed", error);
    throw error;
  }
};

export const listMyCommunityMcpTools = async () => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcpTools.communityMine);
    const data =
      await parseJson<
        ApiEnvelope<{ count: number; items: CommunityMcpCard[] }>
      >(response);
    if (data.status !== "success") {
      throw new Error("Failed to load my community mcp list");
    }
    return { success: true, data: data.data } as McpToolsApiResult<{
      count: number;
      items: CommunityMcpCard[];
    }>;
  } catch (error) {
    log.error("listMyCommunityMcpTools failed", error);
    throw error;
  }
};

export const updateCommunityMcpTool = async (payload: {
  market_id: number;
  name?: string;
  description?: string;
  tags?: string[];
  version?: string;
  registry_json?: Record<string, unknown>;
  mcp_server?: string;
  transport_type?: McpTransportType;
  config_json?: McpContainerConfigPayload;
}) => {
  try {
    const response = await fetchWithAuth(
      API_ENDPOINTS.mcpTools.communityUpdate,
      {
        method: "PUT",
        body: JSON.stringify(payload),
      }
    );
    const data = await parseJson<ApiEnvelope>(response);
    if (data.status !== "success") {
      throw new Error("Failed to update community mcp");
    }
    return { success: true, data: null } as McpToolsApiResult<null>;
  } catch (error) {
    log.error("updateCommunityMcpTool failed", error);
    throw error;
  }
};

export const deleteCommunityMcpTool = async (marketId: number) => {
  try {
    const response = await fetchWithAuth(
      `${API_ENDPOINTS.mcpTools.communityDelete}?market_id=${encodeURIComponent(String(marketId))}`,
      {
        method: "DELETE",
      }
    );
    const data = await parseJson<ApiEnvelope>(response);
    if (data.status !== "success") {
      throw new Error("Failed to delete community mcp");
    }
    return { success: true, data: null } as McpToolsApiResult<null>;
  } catch (error) {
    log.error("deleteCommunityMcpTool failed", error);
    throw error;
  }
};

export const addMcpToolService = async (payload: AddMcpServicePayload) => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcp.add, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const data = await parseJson<ApiEnvelope>(response);
    if (data.status !== "success") {
      throw new Error("Failed to add MCP service");
    }
    return { success: true, data: null } as McpToolsApiResult<null>;
  } catch (error) {
    log.error("addMcpToolService failed", error);
    throw error;
  }
};

export const updateMcpToolService = async (
  payload: UpdateMcpServicePayload
) => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcp.update, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    const data = await parseJson<ApiEnvelope>(response);
    if (data.status !== "success") {
      throw new Error("Failed to update MCP service");
    }
    return { success: true, data: null } as McpToolsApiResult<null>;
  } catch (error) {
    log.error("updateMcpToolService failed", error);
    throw error;
  }
};

export const enableMcpToolService = async (
  payload: ToggleMcpServicePayload
) => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcp.enable, {
      method: "POST",
      body: JSON.stringify({ mcp_id: payload.mcp_id }),
    });
    const data = await parseJson<ApiEnvelope>(response);
    if (data.status !== "success") {
      throw new Error("Failed to update service status");
    }
    return { success: true, data: null } as McpToolsApiResult<null>;
  } catch (error) {
    log.error("enableMcpToolService failed", error);
    throw error;
  }
};

export const disableMcpToolService = async (
  payload: ToggleMcpServicePayload
) => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcp.disable, {
      method: "POST",
      body: JSON.stringify({ mcp_id: payload.mcp_id }),
    });
    const data = await parseJson<ApiEnvelope>(response);
    if (data.status !== "success") {
      throw new Error("Failed to update service status");
    }
    return { success: true, data: null } as McpToolsApiResult<null>;
  } catch (error) {
    log.error("disableMcpToolService failed", error);
    throw error;
  }
};

export const healthcheckMcpToolService = async (
  payload: HealthcheckMcpServicePayload
) => {
  try {
    const query = new URLSearchParams();
    query.set("mcp_id", payload.mcp_id.toString());
    const response = await fetchWithAuth(
      `${API_ENDPOINTS.mcp.healthcheck}?${query.toString()}`,
      {
        method: "GET",
      }
    );
    const data = await parseJson<ApiEnvelope<HealthcheckPayload>>(response);
    if (data.status !== "success") {
      throw new Error("Health check failed");
    }
    return {
      success: true,
      data: data.data,
    } as McpToolsApiResult<HealthcheckPayload | null>;
  } catch (error) {
    log.error("healthcheckMcpToolService failed", error);
    throw error;
  }
};

export const deleteMcpToolService = async (mcpId: number) => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcp.delete(mcpId), {
      method: "DELETE",
    });
    const data = await parseJson<ApiEnvelope>(response);
    if (data.status !== "success") {
      throw new Error("Failed to delete service");
    }
    return { success: true, data: null } as McpToolsApiResult<null>;
  } catch (error) {
    log.error("deleteMcpToolService failed", error);
    throw error;
  }
};

export const listMcpRuntimeTools = async (mcpId: number) => {
  try {
    const query = new URLSearchParams();
    query.set("mcp_id", mcpId.toString());
    const response = await fetchWithAuth(
      `${API_ENDPOINTS.mcp.tools}?${query.toString()}`
    );
    const data = await parseJson<ApiEnvelope>(response);
    if (data.status !== "success") {
      throw new Error("Failed to load MCP tools");
    }
    return {
      success: true,
      data: data.tools as McpTool[],
    } as McpToolsApiResult<McpTool[]>;
  } catch (error) {
    log.error("listMcpRuntimeTools failed", error);
    throw error;
  }
};

// Intentionally keep AddFromConfigApiResult type for backward compatibility in other modules.
