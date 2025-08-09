import { STATUS_CODES } from "@/types/auth";

const API_BASE_URL = '/api';

export const API_ENDPOINTS = {
  user: {
    signup: `${API_BASE_URL}/user/signup`,
    signin: `${API_BASE_URL}/user/signin`,
    refreshToken: `${API_BASE_URL}/user/refresh_token`,
    logout: `${API_BASE_URL}/user/logout`,
    session: `${API_BASE_URL}/user/session`,
    currentUserId: `${API_BASE_URL}/user/current_user_id`,
    serviceHealth: `${API_BASE_URL}/user/service_health`,
  },
  conversation: {
    list: `${API_BASE_URL}/conversation/list`,
    create: `${API_BASE_URL}/conversation/create`,
    save: `${API_BASE_URL}/conversation/save`,
    rename: `${API_BASE_URL}/conversation/rename`,
    detail: (id: number) => `${API_BASE_URL}/conversation/${id}`,
    delete: (id: number) => `${API_BASE_URL}/conversation/${id}`,
    generateTitle: `${API_BASE_URL}/conversation/generate_title`,
    sources: `${API_BASE_URL}/conversation/sources`,
    opinion: `${API_BASE_URL}/conversation/message/update_opinion`,
    messageId: `${API_BASE_URL}/conversation/message/id`,
  },
  agent: {
    run: `${API_BASE_URL}/agent/run`,
    update: `${API_BASE_URL}/agent/update`,
    listMainAgentInfo: `${API_BASE_URL}/agent/list_main_agent_info`,
    list: `${API_BASE_URL}/agent/list`,
    delete: `${API_BASE_URL}/agent`,
    getCreatingSubAgentId: `${API_BASE_URL}/agent/get_creating_sub_agent_id`,
    stop: (conversationId: number) => `${API_BASE_URL}/agent/stop/${conversationId}`,
    export: `${API_BASE_URL}/agent/export`,
    import: `${API_BASE_URL}/agent/import`,
    searchInfo: `${API_BASE_URL}/agent/search_info`,
    relatedAgent: `${API_BASE_URL}/agent/related_agent`,
    deleteRelatedAgent: `${API_BASE_URL}/agent/delete_related_agent`,
  },
  tool: {
    list: `${API_BASE_URL}/tool/list`,
    update: `${API_BASE_URL}/tool/update`,
    search: `${API_BASE_URL}/tool/search`,
    updateTool: `${API_BASE_URL}/tool/scan_tool`,
  },
  prompt: {
    generate: `${API_BASE_URL}/prompt/generate`,
    fineTune: `${API_BASE_URL}/prompt/fine_tune`,
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
    file: (objectName: string, download: string = 'ignore') => `${API_BASE_URL}/file/storage/${objectName}?download=${download}`,
    delete: (objectName: string) => `${API_BASE_URL}/file/storage/${objectName}`,
    preprocess: `${API_BASE_URL}/file/preprocess`,
  },
  proxy: {
    image: (url: string) => `${API_BASE_URL}/image?url=${encodeURIComponent(url)}`,
  },
  model: {
    // Basic health check
    healthcheck: `${API_BASE_URL}/me/healthcheck`,
    
    // Official model service
    officialModelList: `${API_BASE_URL}/me/model/list`,
    officialModelHealthcheck: (modelName: string, timeout: number = 2) => 
      `${API_BASE_URL}/me/model/healthcheck?model_name=${encodeURIComponent(modelName)}&timeout=${timeout}`,
      
    // Custom model service
    customModelList: `${API_BASE_URL}/model/list`,
    customModelCreate: `${API_BASE_URL}/model/create`,
    customModelCreateProvider: `${API_BASE_URL}/model/create_provider`,
    customModelBatchCreate: `${API_BASE_URL}/model/batch_create_models`,
    getProviderSelectedModalList: `${API_BASE_URL}/model/provider/list`,
    customModelDelete: (displayName: string) => `${API_BASE_URL}/model/delete?display_name=${encodeURIComponent(displayName)}`,
    customModelHealthcheck: (displayName: string) => `${API_BASE_URL}/model/healthcheck?display_name=${encodeURIComponent(displayName)}`,
    updateConnectStatus: `${API_BASE_URL}/model/update_connect_status`,
    verifyModelConfig: `${API_BASE_URL}/model/verify_config`,
  },
  knowledgeBase: {
    // Elasticsearch service
    health: `${API_BASE_URL}/indices/health`,
    indices: `${API_BASE_URL}/indices`,
    checkName: (name: string) => `${API_BASE_URL}/indices/check_exist/${name}`,
    listFiles: (indexName: string) => `${API_BASE_URL}/indices/${indexName}/files`,
    indexDetail: (indexName: string) => `${API_BASE_URL}/indices/${indexName}`,
    summary: (indexName: string) => `${API_BASE_URL}/summary/${indexName}/auto_summary`,
    changeSummary: (indexName: string) => `${API_BASE_URL}/summary/${indexName}/summary`,
    getSummary: (indexName: string) => `${API_BASE_URL}/summary/${indexName}/summary`,
    
    // File upload service
    upload: `${API_BASE_URL}/file/upload`,
    process: `${API_BASE_URL}/file/process`,
  },
  config: {
    save: `${API_BASE_URL}/config/save_config`,
    load: `${API_BASE_URL}/config/load_config`,
  },
  tenantConfig: {
    loadKnowledgeList: `${API_BASE_URL}/tenant_config/load_knowledge_list`,
    updateKnowledgeList: `${API_BASE_URL}/tenant_config/update_knowledge_list`,
    deploymentVersion: `${API_BASE_URL}/tenant_config/deployment_version`,
  },
  mcp: {
    tools: `${API_BASE_URL}/mcp/tools/`,
    add: `${API_BASE_URL}/mcp/add`,
    delete: `${API_BASE_URL}/mcp/`,
    list: `${API_BASE_URL}/mcp/list`,
    recover: `${API_BASE_URL}/mcp/recover`,
  },
  memory: {
    // ---------------- Memory configuration ----------------
    config: {
      load: `${API_BASE_URL}/memory/config/load`,
      set: `${API_BASE_URL}/memory/config/set`,
      disableAgentAdd: `${API_BASE_URL}/memory/config/disable_agent`,
      disableAgentRemove: (agentId: string | number) => `${API_BASE_URL}/memory/config/disable_agent/${agentId}`,
      disableUserAgentAdd: `${API_BASE_URL}/memory/config/disable_useragent`,
      disableUserAgentRemove: (agentId: string | number) => `${API_BASE_URL}/memory/config/disable_useragent/${agentId}`,
    },

    // ---------------- Memory CRUD ----------------
    entry: {
      add: `${API_BASE_URL}/memory/add`,
      search: `${API_BASE_URL}/memory/search`,
      list: `${API_BASE_URL}/memory/list`,
      delete: (memoryId: string | number) => `${API_BASE_URL}/memory/delete/${memoryId}`,
      clear: `${API_BASE_URL}/memory/clear`,
    },
  }
};

// Common error handling
export class ApiError extends Error {
  constructor(public code: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

// 重构：拦截器等是不是需要单独文件管理？
// API请求拦截器
export const fetchWithErrorHandling = async (url: string, options: RequestInit = {}) => {
  try {
    const response = await fetch(url, options);

    // 处理HTTP错误
    if (!response.ok) {
      // 检查是否为会话过期错误 (401)
      if (response.status === 401) {
        handleSessionExpired();
        throw new ApiError(STATUS_CODES.TOKEN_EXPIRED, "登录已过期，请重新登录");
      }

      // 处理自定义499错误码 (客户端关闭连接)
      if (response.status === 499) {
        handleSessionExpired();
        throw new ApiError(STATUS_CODES.TOKEN_EXPIRED, "连接已断开，会话可能已过期");
      }

      // 其他HTTP错误
      const errorText = await response.text();
      throw new ApiError(response.status, errorText || `请求失败: ${response.status}`);
    }

    return response;
  } catch (error) {
    // 处理网络错误
    if (error instanceof TypeError && error.message.includes('NetworkError')) {
      console.error('网络错误:', error);
      throw new ApiError(STATUS_CODES.SERVER_ERROR, "网络连接错误，请检查网络连接");
    }

    // 处理连接重置错误
    if (error instanceof TypeError && error.message.includes('Failed to fetch')) {
      console.error('连接错误:', error);

      // 对于用户管理相关的请求，可能是登录过期
      if (url.includes('/user/session') || url.includes('/user/current_user_id')) {
        handleSessionExpired();
        throw new ApiError(STATUS_CODES.TOKEN_EXPIRED, "连接已断开，会话可能已过期");
      } else {
        throw new ApiError(STATUS_CODES.SERVER_ERROR, "服务器连接错误，请稍后重试");
      }
    }

    // 重新抛出其他错误
    throw error;
  }
};

// 处理会话过期的方法
function handleSessionExpired() {
  // 防止重复触发
  if (window.__isHandlingSessionExpired) {
    return;
  }

  // 修复：在首页不触发会话过期事件
  const currentPath = window.location.pathname;
  if (currentPath === '/' || currentPath.startsWith('/?') || 
      currentPath.startsWith('/zh') || currentPath.startsWith('/en')) {
    return;
  }

  // 标记正在处理中
  window.__isHandlingSessionExpired = true;

  // 清除本地存储的会话信息
  if (typeof window !== "undefined") {
    localStorage.removeItem("session");

    // 使用自定义事件通知应用中的其他组件（如SessionExpiredListener）
    if (window.dispatchEvent) {
      // 确保使用与EVENTS.SESSION_EXPIRED常量一致的事件名
      window.dispatchEvent(new CustomEvent('session-expired', {
        detail: { message: "登录已过期，请重新登录" }
      }));
    }

    // 300ms后重置标记，允许将来再次触发
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