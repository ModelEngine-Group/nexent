import log from "@/lib/logger";
import { fetchWithAuth } from "@/lib/auth";
import { MCP_SERVER_TYPE } from "@/const/mcpTools";
import { API_ENDPOINTS } from "@/services/api";
import type {
  AddMcpRuntimeFromConfigPayload,
  AddMcpServicePayload,
  HealthcheckMcpServicePayload,
  MarketMcpCard,
  McpHealthStatus,
  McpServiceItem,
  McpServerType,
  ToggleMcpServicePayload,
  UpdateMcpServicePayload,
} from "@/types/mcpTools";
import type { McpTool } from "@/types/agentConfig";

export type McpToolsApiResult<T> = {
  success: boolean;
  data: T;
  message?: string;
};

export type { MarketMcpCard } from "@/types/mcpTools";

type ApiEnvelope<T = unknown> = {
  status: string;
  message?: string;
  detail?: string;
  data: T;
  tools?: McpTool[];
  results?: Array<{ mcp_url?: string }>;
  mcp_url?: string;
};

const parseJson = async <T = ApiEnvelope>(response: Response): Promise<T> => {
  return (await response.json()) as T;
};

type HealthcheckPayload = {
  health_status: McpHealthStatus;
};

export const fetchMarketMcpCards = async (params: {
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

  const result = await listMarketMcpTools(query);
  if (!result.success || !result.data) {
    return {
      success: false,
      data: { items: [], nextCursor: null as string | null },
      message: result.message,
    } as McpToolsApiResult<{ items: MarketMcpCard[]; nextCursor: string | null }>;
  }

  const payload = result.data;

  return {
    success: true,
    data: {
      items: payload.items,
      nextCursor: payload.nextCursor ?? null,
    },
  } as McpToolsApiResult<{ items: MarketMcpCard[]; nextCursor: string | null }>;
};

export const resolveContainerServerInfo = async (params: {
  serverType: McpServerType;
  serviceUrl: string;
  containerServiceName: string;
  containerPort: number | undefined;
  containerConfigJson: string;
  containerUploadFileList: Array<{ originFileObj?: File }>;
  authorizationToken?: string;
  t: (key: string) => string;
}) => {
  if (params.serverType !== MCP_SERVER_TYPE.CONTAINER) {
    return {
      success: true,
      data: {
        finalServerUrl: params.serviceUrl.trim(),
        containerConfig: undefined,
      },
    } as McpToolsApiResult<{
      finalServerUrl: string;
      containerConfig?: Record<string, unknown>;
    }>;
  }

  let finalServerUrl = `container://${params.containerServiceName.trim()}:${params.containerPort}`;
  const containerConfigPayload: Record<string, unknown> = {
    config_json: params.containerConfigJson.trim() || undefined,
    service_name: params.containerServiceName.trim() || undefined,
    port: params.containerPort,
  };

  if (params.containerUploadFileList.length > 0) {
    const file = params.containerUploadFileList[0]?.originFileObj;
    if (!file) {
      return { success: false, data: null, message: params.t("mcpTools.add.error.imageReadFailed") } as McpToolsApiResult<null>;
    }

    const formData = new FormData();
    formData.append("file", file);
    formData.append("port", String(params.containerPort));
    formData.append("service_name", params.containerServiceName.trim());
    if (params.authorizationToken) {
      formData.append("env_vars", JSON.stringify({ authorization_token: params.authorizationToken }));
    }

    const uploadResult = await uploadMcpRuntimeImage(formData);
    if (!uploadResult.success) {
      return {
        success: false,
        data: null,
        message: uploadResult.message || params.t("mcpTools.add.error.imageUploadFailed"),
      } as McpToolsApiResult<null>;
    }

    const uploadData = uploadResult.data;
    const uploadedMcpUrl = uploadData && typeof uploadData.mcp_url === "string" ? uploadData.mcp_url : undefined;
    finalServerUrl = uploadedMcpUrl || finalServerUrl;
    containerConfigPayload.upload_result = uploadData;

    return {
      success: true,
      data: {
        finalServerUrl,
        containerConfig: containerConfigPayload,
      },
    } as McpToolsApiResult<{ finalServerUrl: string; containerConfig: Record<string, unknown> }>;
  }

  let parsedConfig: unknown;
  try {
    parsedConfig = JSON.parse(params.containerConfigJson);
  } catch {
    return { success: false, data: null, message: params.t("mcpTools.add.error.containerJsonInvalid") } as McpToolsApiResult<null>;
  }

  const parsedMcpServers = (parsedConfig as { mcpServers?: Record<string, { port?: number }> }).mcpServers;
  if (!parsedMcpServers || typeof parsedMcpServers !== "object") {
    return { success: false, data: null, message: params.t("mcpTools.add.error.containerJsonMissingServers") } as McpToolsApiResult<null>;
  }

  const mcpServers = Object.fromEntries(
    Object.entries(parsedMcpServers).map(([key, value]) => {
      return [
        key,
        {
          ...value,
          port: typeof value.port === "number" ? value.port : params.containerPort,
        },
      ];
    })
  );

  const addConfigResult = await addMcpRuntimeFromConfig({ mcpServers });
  if (!addConfigResult.success) {
    return {
      success: false,
      data: null,
      message: addConfigResult.message || params.t("mcpTools.add.error.containerAddFailed"),
    } as McpToolsApiResult<null>;
  }

  const addConfigData = addConfigResult.data;
  const firstResultMcpUrl = addConfigData?.results?.[0]?.mcp_url;
  finalServerUrl = firstResultMcpUrl || finalServerUrl;
  containerConfigPayload.add_from_config_result = addConfigData ?? {};

  return {
    success: true,
    data: {
      finalServerUrl,
      containerConfig: containerConfigPayload,
    },
  } as McpToolsApiResult<{ finalServerUrl: string; containerConfig: Record<string, unknown> }>;
};

export const listMcpTools = async () => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcpTools.list);
    const data = await parseJson<ApiEnvelope<McpServiceItem[]>>(response);
    if (!response.ok || data.status !== "success") {
      return { success: false, data: [], message: data.message || "Failed to load MCP services" } as McpToolsApiResult<McpServiceItem[]>;
    }
    return { success: true, data: data.data } as McpToolsApiResult<McpServiceItem[]>;
  } catch (error) {
    log.error("listMcpTools failed", error);
    return { success: false, data: [], message: "Failed to load MCP services" } as McpToolsApiResult<McpServiceItem[]>;
  }
};

export const listMarketMcpTools = async (query: URLSearchParams) => {
  try {
    const response = await fetchWithAuth(`${API_ENDPOINTS.mcpTools.marketList}?${query.toString()}`);
    const data = await parseJson<ApiEnvelope<{ items: MarketMcpCard[]; nextCursor: string | null }>>(response);
    if (!response.ok || data.status !== "success") {
      return { success: false, data: null, message: data.detail || data.message || "Failed to load market list" } as McpToolsApiResult<null>;
    }
    return { success: true, data: data.data } as McpToolsApiResult<{ items: MarketMcpCard[]; nextCursor: string | null }>;
  } catch (error) {
    log.error("listMarketMcpTools failed", error);
    return { success: false, data: null, message: "Failed to load market list" } as McpToolsApiResult<null>;
  }
};

export const addMcpToolService = async (payload: AddMcpServicePayload) => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcpTools.add, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const data = await parseJson<ApiEnvelope>(response);
    if (!response.ok || data.status !== "success") {
      return { success: false, data: null, message: data.detail || data.message || "Failed to add MCP service" } as McpToolsApiResult<null>;
    }
    return { success: true, data: null } as McpToolsApiResult<null>;
  } catch (error) {
    log.error("addMcpToolService failed", error);
    return { success: false, data: null, message: "Failed to add MCP service" } as McpToolsApiResult<null>;
  }
};

export const updateMcpToolService = async (payload: UpdateMcpServicePayload) => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcpTools.update, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    const data = await parseJson<ApiEnvelope>(response);
    if (!response.ok || data.status !== "success") {
      return { success: false, data: null, message: data.message || "Failed to update MCP service" } as McpToolsApiResult<null>;
    }
    return { success: true, data: null } as McpToolsApiResult<null>;
  } catch (error) {
    log.error("updateMcpToolService failed", error);
    return { success: false, data: null, message: "Failed to update MCP service" } as McpToolsApiResult<null>;
  }
};

export const enableMcpToolService = async (payload: ToggleMcpServicePayload) => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcpTools.enable, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const data = await parseJson<ApiEnvelope>(response);
    if (!response.ok || data.status !== "success") {
      return { success: false, data: null, message: data.message || "Failed to update service status" } as McpToolsApiResult<null>;
    }
    return { success: true, data: null } as McpToolsApiResult<null>;
  } catch (error) {
    log.error("enableMcpToolService failed", error);
    return { success: false, data: null, message: "Failed to update service status" } as McpToolsApiResult<null>;
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
    if (!response.ok || data.status !== "success") {
      return { success: false, data: null, message: data.message || "Health check failed" } as McpToolsApiResult<HealthcheckPayload | null>;
    }
    return { success: true, data: data.data } as McpToolsApiResult<HealthcheckPayload | null>;
  } catch (error) {
    log.error("healthcheckMcpToolService failed", error);
    return { success: false, data: null, message: "Health check failed" } as McpToolsApiResult<HealthcheckPayload | null>;
  }
};

export const deleteMcpToolService = async (name: string) => {
  try {
    const response = await fetchWithAuth(`${API_ENDPOINTS.mcpTools.delete}?name=${encodeURIComponent(name)}`, {
      method: "DELETE",
    });
    const data = await parseJson<ApiEnvelope>(response);
    if (!response.ok || data.status !== "success") {
      return { success: false, data: null, message: data.message || "Failed to delete service" } as McpToolsApiResult<null>;
    }
    return { success: true, data: null } as McpToolsApiResult<null>;
  } catch (error) {
    log.error("deleteMcpToolService failed", error);
    return { success: false, data: null, message: "Failed to delete service" } as McpToolsApiResult<null>;
  }
};

export const listMcpRuntimeTools = async (serviceName: string, mcpUrl: string) => {
  try {
    const query = new URLSearchParams({
      service_name: serviceName,
      mcp_url: mcpUrl,
    });
    const response = await fetchWithAuth(`${API_ENDPOINTS.mcp.tools}?${query.toString()}`, {
      method: "POST",
    });
    const data = await parseJson<ApiEnvelope>(response);
    if (!response.ok || data.status !== "success") {
      return { success: false, data: [], message: data.detail || data.message || "Failed to load MCP tools" } as McpToolsApiResult<McpTool[]>;
    }
    return { success: true, data: data.tools as McpTool[] } as McpToolsApiResult<McpTool[]>;
  } catch (error) {
    log.error("listMcpRuntimeTools failed", error);
    return { success: false, data: [], message: "Failed to load MCP tools" } as McpToolsApiResult<McpTool[]>;
  }
};

export const addMcpRuntimeFromConfig = async (payload: AddMcpRuntimeFromConfigPayload) => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcp.addFromConfig, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const data = await parseJson<ApiEnvelope<{ results?: Array<{ mcp_url?: string }> }>>(response);
    if (!response.ok || data.status !== "success") {
      return { success: false, data: null, message: data.detail || data.message || "Failed to add MCP from config" } as McpToolsApiResult<null>;
    }
    return { success: true, data: data.data } as McpToolsApiResult<{ results?: Array<{ mcp_url?: string }> }>;
  } catch (error) {
    log.error("addMcpRuntimeFromConfig failed", error);
    return { success: false, data: null, message: "Failed to add MCP from config" } as McpToolsApiResult<null>;
  }
};

export const uploadMcpRuntimeImage = async (formData: FormData) => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.mcp.uploadImage, {
      method: "POST",
      body: formData,
    });
    const data = await parseJson<ApiEnvelope<{ mcp_url?: string }>>(response);
    if (!response.ok || data.status !== "success") {
      return { success: false, data: null, message: data.detail || data.message || "Failed to upload image" } as McpToolsApiResult<null>;
    }
    return { success: true, data: data.data } as McpToolsApiResult<{ mcp_url?: string }>;
  } catch (error) {
    log.error("uploadMcpRuntimeImage failed", error);
    return { success: false, data: null, message: "Failed to upload image" } as McpToolsApiResult<null>;
  }
};
