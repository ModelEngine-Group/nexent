import { STATUS_CODES } from "@/const/auth";
import log from "@/lib/logger";
import type { MarketAgentListParams } from "@/types/market";

const API_BASE_URL = "/api";

export const API_ENDPOINTS = {
  user: {
    signup: `${API_BASE_URL}/user/signup`,
    signin: `${API_BASE_URL}/user/signin`,
    refreshToken: `${API_BASE_URL}/user/refresh_token`,
    logout: `${API_BASE_URL}/user/logout`,
    session: `${API_BASE_URL}/user/session`,
    currentUserId: `${API_BASE_URL}/user/current_user_id`,
    serviceHealth: `${API_BASE_URL}/user/service_health`,
    revoke: `${API_BASE_URL}/user/revoke`,
  },
  conversation: {
    list: `${API_BASE_URL}/conversation/list`,
    create: `${API_BASE_URL}/conversation/create`,
    save: `${API_BASE_URL}/conversation/save`,
    rename: `${API_BASE_URL}/conversation/rename`,
    detail: (id: number) => `${API_BASE_URL}/conversation/${id}`,
    delete: (id: number) => `${API_BASE_URL}/conversation/${id}`,
    generateTitle: `${API_BASE_URL}/conversation/generate_title`,
    // TODO: Remove this endpoint
    sources: `${API_BASE_URL}/conversation/sources`,
    opinion: `${API_BASE_URL}/conversation/message/update_opinion`,
    messageId: `${API_BASE_URL}/conversation/message/id`,
  },
  agent: {
    run: `${API_BASE_URL}/agent/run`,
    update: `${API_BASE_URL}/agent/update`,
    list: `${API_BASE_URL}/agent/list`,
    delete: `${API_BASE_URL}/agent`,
    getCreatingSubAgentId: `${API_BASE_URL}/agent/get_creating_sub_agent_id`,
    stop: (conversationId: number) =>
      `${API_BASE_URL}/agent/stop/${conversationId}`,
    export: `${API_BASE_URL}/agent/export`,
    import: `${API_BASE_URL}/agent/import`,
    checkNameBatch: `${API_BASE_URL}/agent/check_name`,
    regenerateNameBatch: `${API_BASE_URL}/agent/regenerate_name`,
    searchInfo: `${API_BASE_URL}/agent/search_info`,
    callRelationship: `${API_BASE_URL}/agent/call_relationship`,
    clearNew: (agentId: string | number) =>
      `${API_BASE_URL}/agent/clear_new/${agentId}`,
  },
  tool: {
    list: `${API_BASE_URL}/tool/list`,
    update: `${API_BASE_URL}/tool/update`,
    search: `${API_BASE_URL}/tool/search`,
    updateTool: `${API_BASE_URL}/tool/scan_tool`,
    validate: `${API_BASE_URL}/tool/validate`,
    loadConfig: (toolId: number) =>
      `${API_BASE_URL}/tool/load_config/${toolId}`,
  },
  prompt: {
    generate: `${API_BASE_URL}/prompt/generate`,
  },
  stt: {
    ws: `/api/voice/stt/ws`,
  },
  tts: {
    ws: `/api/voice/tts/ws`,
  },
  storage: {
    upload: `${API_BASE_URL}/file/storage`,
    files: `${API_BASE_URL}/file/storage`,
    file: (
      objectName: string,
      download: string = "ignore",
      filename?: string
    ) => {
      const queryParams = new URLSearchParams();
      queryParams.append("download", download);
      if (filename) queryParams.append("filename", filename);
      return `${API_BASE_URL}/file/download/${objectName}?${queryParams.toString()}`;
    },
    datamateDownload: (params: {
      url?: string;
      baseUrl?: string;
      datasetId?: string;
      fileId?: string;
      filename?: string;
    }) => {
      const queryParams = new URLSearchParams();
      if (params.url) queryParams.append("url", params.url);
      if (params.baseUrl) queryParams.append("base_url", params.baseUrl);
      if (params.datasetId) queryParams.append("dataset_id", params.datasetId);
      if (params.fileId) queryParams.append("file_id", params.fileId);
      if (params.filename) queryParams.append("filename", params.filename);
      return `${API_BASE_URL}/file/datamate/download?${queryParams.toString()}`;
    },
    delete: (objectName: string) =>
      `${API_BASE_URL}/file/storage/${objectName}`,
    preprocess: `${API_BASE_URL}/file/preprocess`,
  },
  proxy: {
    image: (url: string, format: string = "stream") =>
      `${API_BASE_URL}/image?url=${encodeURIComponent(url)}&format=${format}`,
  },
  model: {
    // Model lists
    officialModelList: `${API_BASE_URL}/model/list`, // ModelEngine models are also in this list
    customModelList: `${API_BASE_URL}/model/list`,

    // Custom model service
    customModelCreate: `${API_BASE_URL}/model/create`,
    customModelCreateProvider: `${API_BASE_URL}/model/provider/create`,
    customModelBatchCreate: `${API_BASE_URL}/model/provider/batch_create`,
    getProviderSelectedModalList: `${API_BASE_URL}/model/provider/list`,
    customModelDelete: (displayName: string) =>
      `${API_BASE_URL}/model/delete?display_name=${encodeURIComponent(
        displayName
      )}`,
    customModelHealthcheck: (displayName: string) =>
      `${API_BASE_URL}/model/healthcheck?display_name=${encodeURIComponent(
        displayName
      )}`,
    verifyModelConfig: `${API_BASE_URL}/model/temporary_healthcheck`,
    updateSingleModel: (displayName: string) =>
      `${API_BASE_URL}/model/update?display_name=${encodeURIComponent(displayName)}`,
    updateBatchModel: `${API_BASE_URL}/model/batch_update`,
    // LLM model list for generation
    llmModelList: `${API_BASE_URL}/model/llm_list`,
  },
  knowledgeBase: {
    // Elasticsearch service
    health: `${API_BASE_URL}/indices/health`,
    indices: `${API_BASE_URL}/indices`,
    checkName: `${API_BASE_URL}/indices/check_exist`,
    listFiles: (indexName: string) =>
      `${API_BASE_URL}/indices/${indexName}/files`,
    indexDetail: (indexName: string) => `${API_BASE_URL}/indices/${indexName}`,
    chunks: (indexName: string) =>
      `${API_BASE_URL}/indices/${indexName}/chunks`,
    chunk: (indexName: string) => `${API_BASE_URL}/indices/${indexName}/chunk`,
    chunkDetail: (indexName: string, chunkId: string) =>
      `${API_BASE_URL}/indices/${indexName}/chunk/${chunkId}`,
    searchHybrid: `${API_BASE_URL}/indices/search/hybrid`,
    summary: (indexName: string) =>
      `${API_BASE_URL}/summary/${indexName}/auto_summary`,
    changeSummary: (indexName: string) =>
      `${API_BASE_URL}/summary/${indexName}/summary`,
    getSummary: (indexName: string) =>
      `${API_BASE_URL}/summary/${indexName}/summary`,

    // File upload service
    upload: `${API_BASE_URL}/file/upload`,
    process: `${API_BASE_URL}/file/process`,
    // Error info service
    getErrorInfo: (indexName: string, pathOrUrl: string) =>
      `${API_BASE_URL}/indices/${indexName}/documents/${encodeURIComponent(
        pathOrUrl
      )}/error-info`,
  },
  datamate: {
    syncDatamateKnowledges: `${API_BASE_URL}/datamate/sync_datamate_knowledges`,
    files: (knowledgeBaseId: string) =>
      `${API_BASE_URL}/datamate/${knowledgeBaseId}/files`,
  },
  config: {
    save: `${API_BASE_URL}/config/save_config`,
    load: `${API_BASE_URL}/config/load_config`,
    saveDataMateUrl: `${API_BASE_URL}/config/save_datamate_url`,
  },
  tenantConfig: {
    deploymentVersion: `${API_BASE_URL}/tenant_config/deployment_version`,
    loadKnowledgeList: `${API_BASE_URL}/tenant_config/knowledge_list`,
    updateKnowledgeList: `${API_BASE_URL}/tenant_config/knowledge_list`,
  } as const,
  mcp: {
    tools: `${API_BASE_URL}/mcp/tools`,
    add: `${API_BASE_URL}/mcp/add`,
    update: `${API_BASE_URL}/mcp/update`,
    delete: `${API_BASE_URL}/mcp`,
    list: `${API_BASE_URL}/mcp/list`,
    healthcheck: `${API_BASE_URL}/mcp/healthcheck`,
    addFromConfig: `${API_BASE_URL}/mcp/add-from-config`,
    uploadImage: `${API_BASE_URL}/mcp/upload-image`,
    containers: `${API_BASE_URL}/mcp/containers`,
    containerLogs: (containerId: string) =>
      `${API_BASE_URL}/mcp/container/${containerId}/logs`,
    deleteContainer: (containerId: string) =>
      `${API_BASE_URL}/mcp/container/${containerId}`,
  },
  memory: {
    // ---------------- Memory configuration ----------------
    config: {
      load: `${API_BASE_URL}/memory/config/load`,
      set: `${API_BASE_URL}/memory/config/set`,
      disableAgentAdd: `${API_BASE_URL}/memory/config/disable_agent`,
      disableAgentRemove: (agentId: string | number) =>
        `${API_BASE_URL}/memory/config/disable_agent/${agentId}`,
      disableUserAgentAdd: `${API_BASE_URL}/memory/config/disable_useragent`,
      disableUserAgentRemove: (agentId: string | number) =>
        `${API_BASE_URL}/memory/config/disable_useragent/${agentId}`,
    },

    // ---------------- Memory CRUD ----------------
    entry: {
      add: `${API_BASE_URL}/memory/add`,
      search: `${API_BASE_URL}/memory/search`,
      list: `${API_BASE_URL}/memory/list`,
      delete: (memoryId: string | number) =>
        `${API_BASE_URL}/memory/delete/${memoryId}`,
      clear: `${API_BASE_URL}/memory/clear`,
    },
  },
  market: {
    agents: (params?: MarketAgentListParams) => {
      const queryParams = new URLSearchParams();
      if (params?.page) queryParams.append("page", params.page.toString());
      if (params?.page_size)
        queryParams.append("page_size", params.page_size.toString());
      if (params?.category) queryParams.append("category", params.category);
      if (params?.tag) queryParams.append("tag", params.tag);
      if (params?.search) queryParams.append("search", params.search);
      if (params?.lang) queryParams.append("lang", (params as any).lang);

      const queryString = queryParams.toString();
      return `${API_BASE_URL}/market/agents${queryString ? `?${queryString}` : ""}`;
    },
    agentDetail: (agentId: number) =>
      `${API_BASE_URL}/market/agents/${agentId}`,
    categories: `${API_BASE_URL}/market/categories`,
    tags: `${API_BASE_URL}/market/tags`,
    mcpServers: (agentId: number) =>
      `${API_BASE_URL}/market/agents/${agentId}/mcp_servers`,
  },
  tenant: {
    list: `${API_BASE_URL}/tenants`,
    create: `${API_BASE_URL}/tenants`,
    detail: (tenantId: string) => `${API_BASE_URL}/tenants/${tenantId}`,
    update: (tenantId: string) => `${API_BASE_URL}/tenants/${tenantId}`,
    delete: (tenantId: string) => `${API_BASE_URL}/tenants/${tenantId}`,
  },
  users: {
    list: `${API_BASE_URL}/users/list`,
    detail: (userId: string) => `${API_BASE_URL}/users/${userId}`,
    update: (userId: string) => `${API_BASE_URL}/users/${userId}`,
    delete: (userId: string) => `${API_BASE_URL}/users/${userId}`,
  },
  groups: {
    create: `${API_BASE_URL}/groups`,
    list: `${API_BASE_URL}/groups/list`,
    detail: (groupId: number) => `${API_BASE_URL}/groups/${groupId}`,
    update: (groupId: number) => `${API_BASE_URL}/groups/${groupId}`,
    delete: (groupId: number) => `${API_BASE_URL}/groups/${groupId}`,
    // Group members
    members: (groupId: number) => `${API_BASE_URL}/groups/${groupId}/members`,
    addMember: (groupId: number) => `${API_BASE_URL}/groups/${groupId}/members`,
    removeMember: (groupId: number, userId: string) =>
      `${API_BASE_URL}/groups/${groupId}/members/${userId}`,
  },
  invitations: {
    list: `${API_BASE_URL}/invitations/list`,
    create: `${API_BASE_URL}/invitations`,
    update: (invitationCode: string) =>
      `${API_BASE_URL}/invitations/${invitationCode}`,
    delete: (invitationCode: string) =>
      `${API_BASE_URL}/invitations/${invitationCode}`,
  },
};

// Common error handling
export class ApiError extends Error {
  constructor(
    public code: number,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// API request interceptor
export const fetchWithErrorHandling = async (
  url: string,
  options: RequestInit = {}
) => {
  try {
    const response = await fetch(url, options);

    // Handle HTTP errors
    if (!response.ok) {
      // Check if it's a session expired error (401)
      if (response.status === 401) {
        handleSessionExpired();
        throw new ApiError(
          STATUS_CODES.TOKEN_EXPIRED,
          "Login expired, please login again"
        );
      }

      // Handle custom 499 error code (client closed connection)
      if (response.status === 499) {
        handleSessionExpired();
        throw new ApiError(
          STATUS_CODES.TOKEN_EXPIRED,
          "Connection disconnected, session may have expired"
        );
      }

      // Handle request entity too large error (413)
      if (response.status === 413) {
        throw new ApiError(
          STATUS_CODES.REQUEST_ENTITY_TOO_LARGE,
          "REQUEST_ENTITY_TOO_LARGE"
        );
      }

      // Other HTTP errors
      const errorText = await response.text();
      throw new ApiError(
        response.status,
        errorText || `Request failed: ${response.status}`
      );
    }

    return response;
  } catch (error) {
    // Handle network errors
    if (error instanceof TypeError && error.message.includes("NetworkError")) {
      log.error("Network error:", error);
      throw new ApiError(
        STATUS_CODES.SERVER_ERROR,
        "Network connection error, please check your network connection"
      );
    }

    // Handle connection reset errors
    if (
      error instanceof TypeError &&
      error.message.includes("Failed to fetch")
    ) {
      log.error("Connection error:", error);

      // For user management related requests, it might be login expiration
      if (
        url.includes("/user/session") ||
        url.includes("/user/current_user_id")
      ) {
        handleSessionExpired();
        throw new ApiError(
          STATUS_CODES.TOKEN_EXPIRED,
          "Connection disconnected, session may have expired"
        );
      } else {
        throw new ApiError(
          STATUS_CODES.SERVER_ERROR,
          "Server connection error, please try again later"
        );
      }
    }

    // Re-throw other errors
    throw error;
  }
};

// Method to handle session expiration
function handleSessionExpired() {
  // Prevent duplicate triggers
  if (window.__isHandlingSessionExpired) {
    return;
  }

  // Mark as processing
  window.__isHandlingSessionExpired = true;

  // Clear locally stored session information
  if (typeof window !== "undefined") {
    localStorage.removeItem("session");

    // Use custom events to notify other components in the app (such as SessionExpiredListener)
    if (window.dispatchEvent) {
      // Ensure using event name consistent with EVENTS.SESSION_EXPIRED constant
      window.dispatchEvent(
        new CustomEvent("session-expired", {
          detail: { message: "Login expired, please login again" },
        })
      );
    }

    // Reset flag after 300ms to allow future triggers
    setTimeout(() => {
      window.__isHandlingSessionExpired = false;
    }, 300);
  }
}

// Add global interface extensions for TypeScript
declare global {
  interface Window {
    __isHandlingSessionExpired?: boolean;
  }
}
