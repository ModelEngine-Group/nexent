const API_BASE_URL = '/api';

export const API_ENDPOINTS = {
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
    list: `${API_BASE_URL}/agent/list`,
    delete: `${API_BASE_URL}/agent`,
    getCreatingSubAgentId: `${API_BASE_URL}/agent/get_creating_sub_agent_id`,
    stop: (conversationId: number) => `${API_BASE_URL}/agent/stop/${conversationId}`,
    export: `${API_BASE_URL}/agent/export`,
    import: `${API_BASE_URL}/agent/import`,
    searchInfo: `${API_BASE_URL}/agent/search_info`,
  },
  tool: {
    list: `${API_BASE_URL}/tool/list`,
    update: `${API_BASE_URL}/tool/update`,
    search: `${API_BASE_URL}/tool/search`,
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
    file: (objectName: string) => `${API_BASE_URL}/file/storage/${objectName}`,
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
    customModelDelete: (displayName: string) => `${API_BASE_URL}/model/delete?display_name=${encodeURIComponent(displayName)}`,
    customModelHealthcheck: (displayName: string) => `${API_BASE_URL}/model/healthcheck?display_name=${encodeURIComponent(displayName)}`,
    verifyModelConfig: `${API_BASE_URL}/model/verify_config`,
  },
  knowledgeBase: {
    // Elasticsearch service
    health: `${API_BASE_URL}/indices/health`,
    indices: `${API_BASE_URL}/indices`,
    indexInfo: (indexName: string) => `${API_BASE_URL}/indices/${indexName}/info`,
    listFiles: (indexName: string, searchRedis: boolean = true) => `${API_BASE_URL}/indices/${indexName}/files?search_redis=${searchRedis}`,
    indexDetail: (indexName: string) => `${API_BASE_URL}/indices/${indexName}`,
    summary: (indexName: string) => `${API_BASE_URL}/summary/${indexName}/auto_summary`,
    changeSummary: (indexName: string) => `${API_BASE_URL}/summary/${indexName}/summary`,
    getSummary: (indexName: string) => `${API_BASE_URL}/summary/${indexName}/summary`,
    
    // File upload service
    upload: `${API_BASE_URL}/file/upload`
  },
  config: {
    save: `${API_BASE_URL}/config/save_config`,
    load: `${API_BASE_URL}/config/load_config`,
  },
  tenantConfig: {
    loadKnowledgeList: `${API_BASE_URL}/tenant_config/load_knowledge_list`,
    updateKnowledgeList: `${API_BASE_URL}/tenant_config/update_knowledge_list`,
  },
  mcp: {
    tools: `${API_BASE_URL}/mcp/tools/`,
    add: `${API_BASE_URL}/mcp/add`,
    delete: `${API_BASE_URL}/mcp/`,
    list: `${API_BASE_URL}/mcp/list`,
    updateTool: `${API_BASE_URL}/mcp/update_tool`,
    recover: `${API_BASE_URL}/mcp/recover`,
  }
};

// Common error handling
export class ApiError extends Error {
  constructor(public code: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

// Add global interface extensions for TypeScript
declare global {
  interface Window {
    __isHandlingSessionExpired?: boolean;
  }
}