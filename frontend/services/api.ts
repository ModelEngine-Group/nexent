import { STATUS_CODES } from "@/const/auth";
import { ErrorCode } from "@/const/errorCode";
import { handleSessionExpired } from "@/lib/session";
import log from "@/lib/logger";
import type {
  AgentRepositoryListingListParams,
  MyEditableAgentListParams,
} from "@/types/agentRepository";
import type {
  MyEditableSkillListParams,
  SkillRepositoryListingListParams,
} from "@/types/skillRepository";
import type { MarketAgentListParams } from "@/types/market";
import type { NotificationListParams } from "@/types/notification";

const API_BASE_URL = "/api";

export const API_ENDPOINTS = {
  user: {
    signup: `${API_BASE_URL}/user/signup`,
    signin: `${API_BASE_URL}/user/signin`,
    refreshToken: `${API_BASE_URL}/user/refresh_token`,
    logout: `${API_BASE_URL}/user/logout`,
    session: `${API_BASE_URL}/user/session`,
    currentUserId: `${API_BASE_URL}/user/current_user_id`,
    currentUserInfo: `${API_BASE_URL}/user/current_user_info`,
    serviceHealth: `${API_BASE_URL}/user/service_health`,
    revoke: `${API_BASE_URL}/user/revoke`,
    tokens: `${API_BASE_URL}/user/tokens`,
    deleteToken: (tokenId: number) => `${API_BASE_URL}/user/tokens/${tokenId}`,
    updatePassword: `${API_BASE_URL}/user/password`,
  },
  oauth: {
    config: `${API_BASE_URL}/user/oauth/config`,
    providers: `${API_BASE_URL}/user/oauth/providers`,
    authorize: `${API_BASE_URL}/user/oauth/authorize`,
    link: `${API_BASE_URL}/user/oauth/link`,
    pending: `${API_BASE_URL}/user/oauth/pending`,
    complete: `${API_BASE_URL}/user/oauth/complete`,
    accounts: `${API_BASE_URL}/user/oauth/accounts`,
    unlink: (provider: string) =>
      `${API_BASE_URL}/user/oauth/accounts/${provider}`,
  },
  cas: {
    config: `${API_BASE_URL}/user/cas/config`,
    login: `${API_BASE_URL}/user/cas/login`,
    renew: `${API_BASE_URL}/user/cas/renew`,
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
  share: {
    createConversation: (conversationId: number) =>
      `${API_BASE_URL}/share/conversation/${conversationId}`,
    detail: (shareId: string) => `${API_BASE_URL}/share/${shareId}`,
    assetPreview: (shareId: string, assetId: string, filename?: string) => {
      const queryParams = new URLSearchParams();
      if (filename) queryParams.append("filename", filename);
      const suffix = queryParams.toString() ? `?${queryParams.toString()}` : "";
      return `${API_BASE_URL}/share/${shareId}/assets/${assetId}/preview${suffix}`;
    },
    assetDownload: (shareId: string, assetId: string, filename?: string) => {
      const queryParams = new URLSearchParams();
      if (filename) queryParams.append("filename", filename);
      const suffix = queryParams.toString() ? `?${queryParams.toString()}` : "";
      return `${API_BASE_URL}/share/${shareId}/assets/${assetId}/download${suffix}`;
    },
  },
  agent: {
    run: `${API_BASE_URL}/agent/run`,
    update: `${API_BASE_URL}/agent/update`,
    list: `${API_BASE_URL}/agent/list`,
    publishedList: `${API_BASE_URL}/agent/published_list`,
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
    byName: (agentName: string) =>
      `${API_BASE_URL}/agent/by-name/${encodeURIComponent(agentName)}`,
    clearNew: (agentId: string | number) =>
      `${API_BASE_URL}/agent/clear_new/${agentId}`,
    generateGuardrailRules: `${API_BASE_URL}/agent/generate_guardrail_rules`,
    publish: (agentId: number) => `${API_BASE_URL}/agent/${agentId}/publish`,
    versions: {
      version: (agentId: number, versionNo: number) =>
        `${API_BASE_URL}/agent/${agentId}/versions/${versionNo}`,
      detail: (agentId: number, versionNo: number) =>
        `${API_BASE_URL}/agent/${agentId}/versions/${versionNo}/detail`,
      list: (agentId: number) => `${API_BASE_URL}/agent/${agentId}/versions`,
      current: (agentId: number) =>
        `${API_BASE_URL}/agent/${agentId}/current_version`,
      rollback: (agentId: number, versionNo: number) =>
        `${API_BASE_URL}/agent/${agentId}/versions/${versionNo}/rollback`,
      compare: (agentId: number) =>
        `${API_BASE_URL}/agent/${agentId}/versions/compare`,
      delete: (agentId: number, versionNo: number) =>
        `${API_BASE_URL}/agent/${agentId}/versions/${versionNo}`,
      update: (agentId: number, versionNo: number) =>
        `${API_BASE_URL}/agent/${agentId}/versions/${versionNo}`,
    },
  },
  agentAutomation: {
    list: `${API_BASE_URL}/agent/automations`,
    detail: (taskId: number) => `${API_BASE_URL}/agent/automations/${taskId}`,
    update: (taskId: number) => `${API_BASE_URL}/agent/automations/${taskId}`,
    delete: (taskId: number) => `${API_BASE_URL}/agent/automations/${taskId}`,
    pause: (taskId: number) =>
      `${API_BASE_URL}/agent/automations/${taskId}/pause`,
    resume: (taskId: number) =>
      `${API_BASE_URL}/agent/automations/${taskId}/resume`,
    run: (taskId: number) => `${API_BASE_URL}/agent/automations/${taskId}/run`,
    runs: (taskId: number) =>
      `${API_BASE_URL}/agent/automations/${taskId}/runs`,
    cancelRun: (runId: number) =>
      `${API_BASE_URL}/agent/automations/runs/${runId}/cancel`,
    deleteRun: (runId: number) =>
      `${API_BASE_URL}/agent/automations/runs/${runId}`,
    proposals: `${API_BASE_URL}/agent/automations/proposals`,
    updateProposal: (proposalId: number) =>
      `${API_BASE_URL}/agent/automations/proposals/${proposalId}`,
    confirmProposal: (proposalId: number) =>
      `${API_BASE_URL}/agent/automations/proposals/${proposalId}/confirm`,
    conversation: (conversationId: number) =>
      `${API_BASE_URL}/conversation/${conversationId}/automation`,
  },
  tool: {
    list: `${API_BASE_URL}/tool/list`,
    update: `${API_BASE_URL}/tool/update`,
    search: `${API_BASE_URL}/tool/search`,
    updateTool: `${API_BASE_URL}/tool/scan_tool`,
    validate: `${API_BASE_URL}/tool/validate`,
    loadConfig: (toolId: number) =>
      `${API_BASE_URL}/tool/load_config/${toolId}`,
    // OpenAPI Service APIs
    openapiService: `${API_BASE_URL}/tool/openapi_service`,
    openapiServices: `${API_BASE_URL}/tool/openapi_services`,
    deleteOpenapiService: (serviceName: string) =>
      `${API_BASE_URL}/tool/openapi_service/${encodeURIComponent(serviceName)}`,
    labels: `${API_BASE_URL}/tool/labels`,
  },
  prompt: {
    generate: `${API_BASE_URL}/prompt/generate`,
    optimize: `${API_BASE_URL}/prompt/optimize`,
  },
  promptTemplates: {
    list: `${API_BASE_URL}/prompt_templates`,
    detail: (templateId: number) =>
      `${API_BASE_URL}/prompt_templates/${templateId}`,
    create: `${API_BASE_URL}/prompt_templates`,
    update: (templateId: number) =>
      `${API_BASE_URL}/prompt_templates/${templateId}`,
    delete: (templateId: number) =>
      `${API_BASE_URL}/prompt_templates/${templateId}`,
  },
  evaluationSets: {
    list: `${API_BASE_URL}/evaluation-sets`,
    create: `${API_BASE_URL}/evaluation-sets`,
    detail: (id: number) => `${API_BASE_URL}/evaluation-sets/${id}`,
    cases: (id: number) => `${API_BASE_URL}/evaluation-sets/${id}/cases`,
    upload: `${API_BASE_URL}/evaluation-sets/upload`,
    template: `${API_BASE_URL}/evaluation-sets/template`,
    delete: (id: number) => `${API_BASE_URL}/evaluation-sets/${id}`,
  },
  agentEvaluations: {
    create: `${API_BASE_URL}/agent-evaluations`,
    listByAgent: `${API_BASE_URL}/agent-evaluations`,
    detail: (id: number) => `${API_BASE_URL}/agent-evaluations/${id}`,
    cases: (id: number) => `${API_BASE_URL}/agent-evaluations/${id}/cases`,
    report: (id: number) => `${API_BASE_URL}/agent-evaluations/${id}/report`,
    delete: (id: number) => `${API_BASE_URL}/agent-evaluations/${id}`,
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
    preview: (objectName: string, filename?: string) => {
      const queryParams = new URLSearchParams();
      if (filename) queryParams.append("filename", filename);
      const queryString = queryParams.toString();
      const suffix = queryString ? `?${queryString}` : "";
      return `${API_BASE_URL}/file/preview/${objectName}${suffix}`;
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
    customModelHealthcheck: (displayName: string, modelType: string) =>
      `${API_BASE_URL}/model/healthcheck?display_name=${encodeURIComponent(
        displayName
      )}&model_type=${encodeURIComponent(modelType)}`,
    verifyModelConfig: `${API_BASE_URL}/model/temporary_healthcheck`,
    suggestCapacity: `${API_BASE_URL}/model/suggest-capacity`,
    capacityCoverage: `${API_BASE_URL}/model/capacity-coverage`,
    updateSingleModel: (displayName: string) =>
      `${API_BASE_URL}/model/update?display_name=${encodeURIComponent(displayName)}`,
    updateBatchModel: `${API_BASE_URL}/model/batch_update`,
    // LLM model list for generation
    llmModelList: `${API_BASE_URL}/model/llm_list`,
    // Manage tenant model operations
    manageModelList: `${API_BASE_URL}/model/manage/list`,
    manageModelCreate: `${API_BASE_URL}/model/manage/create`,
    manageModelBatchCreate: `${API_BASE_URL}/model/manage/batch_create`,
    manageModelHealthcheck: `${API_BASE_URL}/model/manage/healthcheck`,
    manageModelUpdate: (displayName: string) =>
      `${API_BASE_URL}/model/manage/update?display_name=${encodeURIComponent(displayName)}`,
    manageModelDelete: (displayName: string) =>
      `${API_BASE_URL}/model/manage/delete?display_name=${encodeURIComponent(displayName)}`,
    manageProviderModelList: `${API_BASE_URL}/model/manage/provider/list`,
    manageProviderModelCreate: `${API_BASE_URL}/model/manage/provider/create`,
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
    // Update knowledge base info
    updateIndex: (indexName: string) => `${API_BASE_URL}/indices/${indexName}`,
    searchHybrid: `${API_BASE_URL}/indices/search/hybrid`,
    summary: (indexName: string) =>
      `${API_BASE_URL}/summary/${indexName}/auto_summary`,
    changeSummary: (indexName: string) =>
      `${API_BASE_URL}/summary/${indexName}/summary`,
    getSummary: (indexName: string) =>
      `${API_BASE_URL}/summary/${indexName}/summary`,
    updateSummaryFrequency: (indexName: string) =>
      `${API_BASE_URL}/indices/${indexName}/summary_frequency`,

    // File upload service
    upload: `${API_BASE_URL}/file/upload`,
    process: `${API_BASE_URL}/file/process`,
    // Error info service
    getErrorInfo: (indexName: string, pathOrUrl: string) =>
      `${API_BASE_URL}/indices/${indexName}/documents/${encodeURIComponent(
        pathOrUrl
      )}/error-info`,
    // Embedding model status and configuration
    embeddingModelStatus: (indexName: string) =>
      `${API_BASE_URL}/indices/${indexName}/embedding-model-status`,
    updateEmbeddingModel: (indexName: string) =>
      `${API_BASE_URL}/indices/${indexName}/embedding-model`,
  },
  dify: {
    datasets: `${API_BASE_URL}/dify/datasets`,
  },
  ragflow: {
    datasets: `${API_BASE_URL}/ragflow/datasets`,
  },
  idata: {
    knowledgeSpaces: `${API_BASE_URL}/idata/knowledge-space`,
    datasets: `${API_BASE_URL}/idata/datasets`,
  },
  datamate: {
    syncDatamateKnowledges: `${API_BASE_URL}/datamate/sync_datamate_knowledges`,
    testConnection: `${API_BASE_URL}/datamate/test_connection`,
    files: (knowledgeBaseId: string) =>
      `${API_BASE_URL}/datamate/${knowledgeBaseId}/files`,
  },
  haotian: {
    knowledgeSets: `${API_BASE_URL}/haotian/knowledge-sets`,
    testConnection: `${API_BASE_URL}/haotian/test-connection`,
  },
  aidp: {
    knowledgeBases: `${API_BASE_URL}/aidp/knowledge-bases`,
    knowledgeBasesAll: `${API_BASE_URL}/aidp/knowledge-bases-all`,
  },
  config: {
    save: `${API_BASE_URL}/config/save_config`,
    load: `${API_BASE_URL}/config/load_config`,
    saveDataMateUrl: `${API_BASE_URL}/config/save_datamate_url`,
  },
  tenantConfig: {
    loadKnowledgeList: `${API_BASE_URL}/tenant_config/load_knowledge_list`,
    updateKnowledgeList: `${API_BASE_URL}/tenant_config/update_knowledge_list`,
    deploymentVersion: `${API_BASE_URL}/tenant_config/deployment_version`,
  },
  mcp: {
    tools: `${API_BASE_URL}/mcp/tools`,
    add: `${API_BASE_URL}/mcp/add`,
    update: `${API_BASE_URL}/mcp/update`,
    delete: (mcpId: number) => `${API_BASE_URL}/mcp/${mcpId}`,
    list: `${API_BASE_URL}/mcp/list`,
    healthcheck: `${API_BASE_URL}/mcp/healthcheck`,
    addFromConfig: `${API_BASE_URL}/mcp/add-from-config`,
    uploadImage: `${API_BASE_URL}/mcp/upload-image`,
    containers: `${API_BASE_URL}/mcp/containers`,
    containerLogs: (containerId: string) =>
      `${API_BASE_URL}/mcp/container/${containerId}/logs`,
    deleteContainer: (containerId: string) =>
      `${API_BASE_URL}/mcp/container/${containerId}`,
    record: (mcpId: number) => `${API_BASE_URL}/mcp/record/${mcpId}`,
    refreshTools: `${API_BASE_URL}/mcp/refresh-tools`,
    portCheck: `${API_BASE_URL}/mcp/port/check`,
    portSuggest: `${API_BASE_URL}/mcp/port/suggest`,
    enable: `${API_BASE_URL}/mcp/enable`,
    disable: `${API_BASE_URL}/mcp/disable`,
    testConnection: `${API_BASE_URL}/mcp/test-connection`,
  },
  // A2A Client endpoints
  a2a: {
    // External agent discovery
    discoverUrl: `${API_BASE_URL}/a2a/client/discover/url`,
    discoverNacos: `${API_BASE_URL}/a2a/client/discover/nacos`,
    // External agent management
    agents: `${API_BASE_URL}/a2a/client/agents`,
    agent: (agentId: string) => `${API_BASE_URL}/a2a/client/agents/${agentId}`,
    agentRefresh: (agentId: string) =>
      `${API_BASE_URL}/a2a/client/agents/${agentId}/refresh`,
    agentProtocol: (agentId: string) =>
      `${API_BASE_URL}/a2a/client/agents/${agentId}/protocol`,
    // External agent relations
    relations: `${API_BASE_URL}/a2a/client/relations`,
    relation: (localAgentId: number, externalAgentId: number) =>
      `${API_BASE_URL}/a2a/client/relations?local_agent_id=${localAgentId}&external_agent_id=${externalAgentId}`,
    subAgents: (localAgentId: number) =>
      `${API_BASE_URL}/a2a/client/sub-agents/${localAgentId}`,
    externalRelations: (localAgentId: number) =>
      `${API_BASE_URL}/a2a/client/relations/${localAgentId}`,
    // Nacos config management
    nacosConfigs: `${API_BASE_URL}/a2a/client/nacos-configs`,
    nacosConfig: (configId: string) =>
      `${API_BASE_URL}/a2a/client/nacos-configs/${configId}`,
    nacosTestConnection: `${API_BASE_URL}/a2a/client/nacos-configs/test-connection`,
    // A2A Server management
    serverAgents: `${API_BASE_URL}/a2a/management/agents`,
    serverAgent: (agentId: number) =>
      `${API_BASE_URL}/a2a/management/agents/${agentId}`,
    serverAgentEnable: (agentId: number) =>
      `${API_BASE_URL}/a2a/management/agents/${agentId}/enable`,
    serverAgentDisable: (agentId: number) =>
      `${API_BASE_URL}/a2a/management/agents/${agentId}/disable`,
    serverAgentSettings: (agentId: number) =>
      `${API_BASE_URL}/a2a/management/agents/${agentId}/settings`,
    agentChat: (agentId: string) =>
      `${API_BASE_URL}/a2a/client/agents/${agentId}/chat`,
  },
  skills: {
    list: `${API_BASE_URL}/skills`,
    official: `${API_BASE_URL}/skills/official`,
    upload: `${API_BASE_URL}/skills/upload`,
    get: (skillName: string) => `${API_BASE_URL}/skills/${skillName}`,
    getById: (skillId: number) => `${API_BASE_URL}/skills/${skillId}`,
    update: (skillName: string) => `${API_BASE_URL}/skills/${skillName}`,
    updateById: (skillId: number) => `${API_BASE_URL}/skills/${skillId}`,
    updateUpload: (skillName: string) =>
      `${API_BASE_URL}/skills/${skillName}/upload`,
    delete: (skillName: string) => `${API_BASE_URL}/skills/${skillName}`,
    deleteFile: (skillName: string, filePath: string) =>
      `${API_BASE_URL}/skills/${skillName}/files/${filePath}`,
    files: (skillName: string) => `${API_BASE_URL}/skills/${skillName}/files`,
    fileContent: (skillName: string, filePath: string) =>
      `${API_BASE_URL}/skills/${skillName}/files/${filePath}`,
    instanceList: `${API_BASE_URL}/skills/instance/list`,
    instanceUpdate: `${API_BASE_URL}/skills/instance/update`,
    scan: `${API_BASE_URL}/skills/scan_skill`,
    create: `${API_BASE_URL}/skills`,
    createStream: `${API_BASE_URL}/skills/create`,
    stopCreate: (taskId: string) => `${API_BASE_URL}/skills/stop/${taskId}`,
    install: `${API_BASE_URL}/skills/install`,
  },
  mcpTools: {
    // Community and Registry endpoints remain under /mcp-tools prefix
    registryList: `${API_BASE_URL}/mcp-tools/registry/list`,
    communityList: `${API_BASE_URL}/mcp-tools/community/list`,
    communityPublish: `${API_BASE_URL}/mcp-tools/community/publish`,
    communityUpdate: `${API_BASE_URL}/mcp-tools/community/update`,
    communityDelete: `${API_BASE_URL}/mcp-tools/community/delete`,
    communityMine: `${API_BASE_URL}/mcp-tools/community/mine`,
    communityReviewList: `${API_BASE_URL}/mcp-tools/community/review/list`,
    communityReviewApprove: `${API_BASE_URL}/mcp-tools/community/review/approve`,
    communityReviewReject: `${API_BASE_URL}/mcp-tools/community/review/reject`,
    communityTagsStats: `${API_BASE_URL}/mcp-tools/community/tags/stats`,
    communityDownload: (marketId: number) =>
      `${API_BASE_URL}/mcp-tools/community/${marketId}/download`,
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
  agentRepository: {
    listings: (params?: AgentRepositoryListingListParams) => {
      const queryParams = new URLSearchParams();
      if (params?.status) queryParams.append("status", params.status);
      if (params?.agent_id != null) {
        queryParams.append("agent_id", String(params.agent_id));
      }
      if (params?.page != null) {
        queryParams.append("page", String(params.page));
      }
      if (params?.page_size != null) {
        queryParams.append("page_size", String(params.page_size));
      }
      if (params?.search?.trim()) {
        queryParams.append("search", params.search.trim());
      }
      const queryString = queryParams.toString();
      return `${API_BASE_URL}/repository/agent${queryString ? `?${queryString}` : ""}`;
    },
    mineAgents: (params?: MyEditableAgentListParams) => {
      const queryParams = new URLSearchParams();
      if (params?.ownership) {
        queryParams.append("ownership", params.ownership);
      }
      if (params?.page != null) {
        queryParams.append("page", String(params.page));
      }
      if (params?.page_size != null) {
        queryParams.append("page_size", String(params.page_size));
      }
      if (params?.search?.trim()) {
        queryParams.append("search", params.search.trim());
      }
      if (params?.new_agent_padding) {
        queryParams.append("new_agent_padding", "true");
      }
      if (params?.agent_id != null) {
        queryParams.append("agent_id", String(params.agent_id));
      }
      const queryString = queryParams.toString();
      return `${API_BASE_URL}/repository/agent/mine${queryString ? `?${queryString}` : ""}`;
    },
    detail: (agentRepositoryId: number) =>
      `${API_BASE_URL}/repository/agent/${agentRepositoryId}`,
    importPrecheck: (agentRepositoryId: number) =>
      `${API_BASE_URL}/repository/agent/${agentRepositoryId}/import_precheck`,
    import: (agentRepositoryId: number) =>
      `${API_BASE_URL}/repository/agent/${agentRepositoryId}/import`,
    updateStatus: (agentRepositoryId: number) =>
      `${API_BASE_URL}/repository/agent/${agentRepositoryId}/status`,
    createListing: (agentId: number, versionNo: number) =>
      `${API_BASE_URL}/repository/agent/${agentId}/versions/${versionNo}`,
  },
  skillRepository: {
    listings: (params?: SkillRepositoryListingListParams) => {
      const queryParams = new URLSearchParams();
      if (params?.status) queryParams.append("status", params.status);
      if (params?.skill_id != null) {
        queryParams.append("skill_id", String(params.skill_id));
      }
      if (params?.category_id != null) {
        queryParams.append("category_id", String(params.category_id));
      }
      if (params?.page != null) {
        queryParams.append("page", String(params.page));
      }
      if (params?.page_size != null) {
        queryParams.append("page_size", String(params.page_size));
      }
      if (params?.search?.trim()) {
        queryParams.append("search", params.search.trim());
      }
      if (params?.sort_by_update_time) {
        queryParams.append("sort_by_update_time", "true");
      }
      const queryString = queryParams.toString();
      return `${API_BASE_URL}/repository/skill${queryString ? `?${queryString}` : ""}`;
    },
    mineSkills: (params?: MyEditableSkillListParams) => {
      const queryParams = new URLSearchParams();
      if (params?.ownership) {
        queryParams.append("ownership", params.ownership);
      }
      if (params?.page != null) {
        queryParams.append("page", String(params.page));
      }
      if (params?.page_size != null) {
        queryParams.append("page_size", String(params.page_size));
      }
      if (params?.search?.trim()) {
        queryParams.append("search", params.search.trim());
      }
      if (params?.new_skill_padding) {
        queryParams.append("new_skill_padding", "true");
      }
      const queryString = queryParams.toString();
      return `${API_BASE_URL}/repository/skill/mine${queryString ? `?${queryString}` : ""}`;
    },
    detail: (skillRepositoryId: number) =>
      `${API_BASE_URL}/repository/skill/${skillRepositoryId}`,
    install: (skillRepositoryId: number) =>
      `${API_BASE_URL}/repository/skill/${skillRepositoryId}/install`,
    updateStatus: (skillRepositoryId: number) =>
      `${API_BASE_URL}/repository/skill/${skillRepositoryId}/status`,
    createListing: (skillId: number) =>
      `${API_BASE_URL}/repository/skill/${skillId}`,
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
    list: `${API_BASE_URL}/tenants/tenant-list`,
    create: `${API_BASE_URL}/tenants`,
    detail: (tenantId: string) => `${API_BASE_URL}/tenants/${tenantId}`,
    update: (tenantId: string) => `${API_BASE_URL}/tenants/${tenantId}`,
    delete: (tenantId: string) => `${API_BASE_URL}/tenants/${tenantId}`,
  },
  // Quota management endpoints
  quota: {
    // Tenant-level quota
    config: (tenantId: string) => `${API_BASE_URL}/tenants/${tenantId}/quota`,
    usage: (tenantId: string) => `${API_BASE_URL}/tenants/${tenantId}/quota/usage`,
    // Platform-level quota (SU/ASSET_OWNER only)
    platformOverview: `${API_BASE_URL}/platform/quota/overview`,
    platformCapacity: `${API_BASE_URL}/platform/quota/capacity`,
    platformTenantQuota: (tenantId: string) => `${API_BASE_URL}/platform/quota/tenants/${tenantId}`,
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
    default: (tenantId: string) =>
      `${API_BASE_URL}/groups/tenants/${tenantId}/default`,
  },
  invitations: {
    list: `${API_BASE_URL}/invitations/list`,
    create: `${API_BASE_URL}/invitations`,
    update: (invitationCode: string) =>
      `${API_BASE_URL}/invitations/${invitationCode}`,
    delete: (invitationCode: string) =>
      `${API_BASE_URL}/invitations/${invitationCode}`,
    check: (invitationCode: string) =>
      `${API_BASE_URL}/invitations/${invitationCode}/check`,
  },
  monitoring: {
    models: `${API_BASE_URL}/monitoring/models`,
    status: `${API_BASE_URL}/monitoring/status`,
  },
  notifications: {
    list: (params?: NotificationListParams) => {
      const queryParams = new URLSearchParams();
      if (params?.only_unread) {
        queryParams.append("only_unread", "true");
      }
      if (params?.page != null) {
        queryParams.append("page", String(params.page));
      }
      if (params?.page_size != null) {
        queryParams.append("page_size", String(params.page_size));
      }
      const queryString = queryParams.toString();
      return `${API_BASE_URL}/notifications${queryString ? `?${queryString}` : ""}`;
    },
    markRead: `${API_BASE_URL}/notifications/read`,
  },
};

// Common error handling
export class ApiError extends Error {
  constructor(
    public code: string | number,
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
      // Try to parse JSON response for business error code first
      let errorCode = response.status;
      let errorMessage = `Request failed: ${response.status}`;
      const errorText = await response.text();

      try {
        const errorData = JSON.parse(errorText);
        const errorDetail =
          errorData?.detail && typeof errorData.detail === "object"
            ? errorData.detail
            : errorData?.message && typeof errorData.message === "object"
              ? errorData.message
              : errorData;
        if (errorDetail?.code) {
          errorCode = errorDetail.code;
          errorMessage = errorDetail.message || errorMessage;
        } else {
          errorMessage = errorText || errorMessage;
        }
      } catch {
        // Not JSON, use text as message
        errorMessage = errorText || errorMessage;
      }

      // Check if it's a session expiration error based on business error code
      // TOKEN_EXPIRED = "000203", TOKEN_INVALID = "000204"
      const errorCodeStr = String(errorCode);
      if (
        errorCodeStr === ErrorCode.TOKEN_EXPIRED ||
        errorCodeStr === ErrorCode.TOKEN_INVALID
      ) {
        handleSessionExpired();
        throw new ApiError(errorCode, errorMessage);
      }

      // Handle HTTP 401 - trigger session expired modal for all unauthorized errors
      if (response.status === 401) {
        handleSessionExpired();
        throw new ApiError(errorCode, errorMessage);
      }

      // Handle custom 499 error code (client closed connection)
      if (response.status === 499) {
        handleSessionExpired();
        throw new ApiError(
          ErrorCode.TOKEN_EXPIRED,
          "Connection disconnected, session may have expired"
        );
      }

      // Handle request entity too large error (413)
      if (response.status === 413) {
        throw new ApiError(
          ErrorCode.FILE_TOO_LARGE,
          "File size exceeds limit."
        );
      }

      throw new ApiError(errorCode, errorMessage);
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

// Add global interface extensions for TypeScript
declare global {
  interface Window {
    __isHandlingSessionExpired?: boolean;
  }
}
