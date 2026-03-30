import log from "@/lib/logger";
import { fetchWithAuth } from "@/lib/auth";
import { MCP_TRANSPORT_TYPE } from "@/const/mcpTools";
import { API_ENDPOINTS } from "@/services/api";
import type {
  AddMcpRuntimeFromConfigPayload,
  AddMcpServicePayload,
  HealthcheckMcpServicePayload,
  RegistryMcpCard,
  CommunityMcpCard,
  McpHealthStatus,
  McpServiceItem,
  McpTransportType,
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

type AddFromConfigApiResult = {
  status: string;
  message?: string;
  results?: Array<{ service_name?: string; mcp_url?: string }>;
  errors?: string[] | null;
};

type AddContainerMcpToolPayload = {
  name: string;
  description: string;
  tags: string[];
  source?: "local" | "community" | "market";
  authorization_token?: string;
  registry_json?: Record<string, unknown>;
  port: number;
  mcp_config: AddMcpRuntimeFromConfigPayload;
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

  const result = await listRegistryMcpTools(query);
  const payload = result.data;

  return {
    success: true,
    data: {
      items: payload.items,
      nextCursor: payload.nextCursor ?? null,
    },
  } as McpToolsApiResult<{ items: RegistryMcpCard[]; nextCursor: string | null }>;
};

export const fetchCommunityMcpCards = async (params: {
  search?: string;
  cursor?: string | null;
  transportType?: "http" | "sse" | "stdio";
  limit?: number;
}) => {
  const result = await listCommunityMcpTools({
    search: params.search?.trim() || undefined,
    cursor: params.cursor || undefined,
    transport_type: params.transportType,
    limit: params.limit ?? 30,
  });

  return {
    success: true,
    data: {
      items: result.data.items,
      nextCursor: result.data.nextCursor ?? null,
    },
  } as McpToolsApiResult<{ items: CommunityMcpCard[]; nextCursor: string | null }>;
};

export const resolveContainerServerInfo = async (params: {
  transportType: McpTransportType;
  serviceUrl: string;
  containerPort: number | undefined;
  containerConfigJson: string;
}): Promise<
  McpToolsApiResult<{
    finalServerUrl: string;
    containerConfig?: Record<string, unknown>;
    runtimeService?: { name?: string; url?: string };
    mcpConfig?: AddMcpRuntimeFromConfigPayload;
  }>
> => {
  if (params.transportType !== MCP_TRANSPORT_TYPE.STDIO) {
    return {
      success: true,
      data: {
        finalServerUrl: params.serviceUrl.trim(),
        containerConfig: undefined,
        runtimeService: undefined,
        mcpConfig: undefined,
      },
    };
  }

  let finalServerUrl = `container://mcp-container:${params.containerPort}`;
  const containerConfigPayload: Record<string, unknown> = {
    config_json: params.containerConfigJson.trim() || undefined,
    port: params.containerPort,
  };

  let parsedConfig: unknown;
  try {
    parsedConfig = JSON.parse(params.containerConfigJson);
  } catch {
    throw new Error("Invalid container config JSON");
  }

  const parsedMcpServers = (parsedConfig as { mcpServers?: Record<string, { port?: number }> }).mcpServers;
  if (!parsedMcpServers || typeof parsedMcpServers !== "object") {
    throw new Error("Missing mcpServers in container config");
  }

  const mcpConfigPayload = parsedConfig as AddMcpRuntimeFromConfigPayload;
  containerConfigPayload.mcp_config = mcpConfigPayload;

  return {
    success: true,
    data: {
      finalServerUrl,
      containerConfig: containerConfigPayload,
      runtimeService: undefined,
      mcpConfig: mcpConfigPayload,
    },
  };
};

export const addContainerMcpToolService = async (payload: AddContainerMcpToolPayload) => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcpTools.addContainer, {
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

export const listMcpTools = async () => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcpTools.list);
    const data = await parseJson<ApiEnvelope<McpServiceItem[]>>(response);
    if (data.status !== "success") {
      throw new Error("Failed to load MCP services");
    }
    return { success: true, data: data.data } as McpToolsApiResult<McpServiceItem[]>;
  } catch (error) {
    log.error("listMcpTools failed", error);
    throw error;
  }
};

export const listRegistryMcpTools = async (query: URLSearchParams) => {
  try {
    const response = await fetchWithAuth(`${API_ENDPOINTS.mcpTools.registryList}?${query.toString()}`);
    const data = await parseJson<{ servers?: RegistryMcpCard[]; metadata?: { nextCursor?: string | null } }>(response);
    if (!data || !Array.isArray(data.servers)) {
      throw new Error("Failed to load registry mcp list");
    }
    return {
      success: true,
      data: {
        items: data.servers,
        nextCursor: data.metadata?.nextCursor ?? null,
      },
    } as McpToolsApiResult<{ items: RegistryMcpCard[]; nextCursor: string | null }>;
  } catch (error) {
    log.error("listRegistryMcpTools failed", error);
    throw error;
  }
};

export const listCommunityMcpTools = async (payload: {
  search?: string;
  transport_type?: "http" | "sse" | "stdio";
  cursor?: string;
  limit?: number;
}) => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcpTools.communityList, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const data = await parseJson<ApiEnvelope<{ items: CommunityMcpCard[]; nextCursor: string | null }>>(response);
    if (data.status !== "success") {
      throw new Error("Failed to load community mcp list");
    }
    return { success: true, data: data.data } as McpToolsApiResult<{ items: CommunityMcpCard[]; nextCursor: string | null }>;
  } catch (error) {
    log.error("listCommunityMcpTools failed", error);
    throw error;
  }
};

export const publishCommunityMcpTool = async (mcpId: number) => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcpTools.communityPublish, {
      method: "POST",
      body: JSON.stringify({ mcp_id: mcpId }),
    });
    const data = await parseJson<ApiEnvelope<{ community_id: number }>>(response);
    if (data.status !== "success") {
      throw new Error("Failed to publish community mcp");
    }
    return { success: true, data: data.data } as McpToolsApiResult<{ community_id: number }>;
  } catch (error) {
    log.error("publishCommunityMcpTool failed", error);
    throw error;
  }
};

export const listMyCommunityMcpTools = async () => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcpTools.communityMine);
    const data = await parseJson<ApiEnvelope<{ count: number; items: CommunityMcpCard[] }>>(response);
    if (data.status !== "success") {
      throw new Error("Failed to load my community mcp list");
    }
    return { success: true, data: data.data } as McpToolsApiResult<{ count: number; items: CommunityMcpCard[] }>;
  } catch (error) {
    log.error("listMyCommunityMcpTools failed", error);
    throw error;
  }
};

export const updateCommunityMcpTool = async (payload: {
  community_id: number;
  name?: string;
  description?: string;
  tags?: string[];
  version?: string;
  registry_json?: Record<string, unknown>;
}) => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcpTools.communityUpdate, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
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

export const deleteCommunityMcpTool = async (communityId: number) => {
  try {
    const response = await fetchWithAuth(
      `${API_ENDPOINTS.mcpTools.communityDelete}?community_id=${encodeURIComponent(String(communityId))}`,
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
    const response = await fetchWithAuth(API_ENDPOINTS.mcpTools.add, {
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

export const updateMcpToolService = async (payload: UpdateMcpServicePayload) => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcpTools.update, {
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

export const enableMcpToolService = async (payload: ToggleMcpServicePayload) => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcpTools.enable, {
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

export const disableMcpToolService = async (payload: ToggleMcpServicePayload) => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcpTools.disable, {
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

export const healthcheckMcpToolService = async (payload: HealthcheckMcpServicePayload) => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcpTools.healthcheck, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const data = await parseJson<ApiEnvelope<HealthcheckPayload>>(
      response
    );
    if (data.status !== "success") {
      throw new Error("Health check failed");
    }
    return { success: true, data: data.data } as McpToolsApiResult<HealthcheckPayload | null>;
  } catch (error) {
    log.error("healthcheckMcpToolService failed", error);
    throw error;
  }
};

export const deleteMcpToolService = async (mcpId: number) => {
  try {
    const response = await fetchWithAuth(`${API_ENDPOINTS.mcpTools.delete}?mcp_id=${encodeURIComponent(String(mcpId))}`, {
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
    const response = await fetchWithAuth(API_ENDPOINTS.mcpTools.tools, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ mcp_id: mcpId }),
    });
    const data = await parseJson<ApiEnvelope>(response);
    if (data.status !== "success") {
      throw new Error("Failed to load MCP tools");
    }
    return { success: true, data: data.tools as McpTool[] } as McpToolsApiResult<McpTool[]>;
  } catch (error) {
    log.error("listMcpRuntimeTools failed", error);
    throw error;
  }
};

// Intentionally keep AddFromConfigApiResult type for backward compatibility in other modules.
