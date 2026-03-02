// Unified encapsulation of knowledge base related API calls

import i18n from "i18next";

import { API_ENDPOINTS } from "./api";

import { NAME_CHECK_STATUS } from "@/const/agentConfig";
import { FILE_TYPES, EXTENSION_TO_TYPE_MAP } from "@/const/knowledgeBase";
import {
  Document,
  KnowledgeBase,
  KnowledgeBaseCreateParams,
  KnowledgeBasesWithDataMateStatus,
  DataMateSyncError,
} from "@/types/knowledgeBase";
import { getAuthHeaders, fetchWithAuth } from "@/lib/auth";
import { configStore } from "@/lib/config";
import log from "@/lib/logger";

// @ts-ignore
const fetch: typeof fetchWithAuth = fetchWithAuth;

// Knowledge base service class
class KnowledgeBaseService {
  // Check Elasticsearch health (force refresh, no caching for setup page)
  async checkHealth(): Promise<boolean> {
    try {
      // Force refresh in setup page, no caching
      const response = await fetch(API_ENDPOINTS.knowledgeBase.health, {
        headers: getAuthHeaders(),
      });
      const data = await response.json();

      const isHealthy =
        data.status === "healthy" && data.elasticsearch === "connected";

      // No longer update cache, get latest status every time

      return isHealthy;
    } catch (error) {
      log.error("Elasticsearch health check failed:", error);
      // No longer cache error status
      return false;
    }
  }

  // Sync Dify knowledge bases
  async syncDifyKnowledgeBases(
    difyApiBase: string,
    apiKey: string
  ): Promise<{
    indices: string[];
    count: number;
    indices_info: any[];
  }> {
    try {
      // Call backend proxy endpoint to avoid CORS issues
      const url = new URL(API_ENDPOINTS.dify.datasets, window.location.origin);
      url.searchParams.set("dify_api_base", difyApiBase);
      url.searchParams.set("api_key", apiKey);

      const response = await fetch(url.toString(), {
        method: "GET",
        headers: getAuthHeaders(),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Failed to fetch Dify datasets");
      }

      const result = await response.json();
      return {
        indices: result.indices || [],
        count: result.count || 0,
        indices_info: result.indices_info || [],
      };
    } catch (error) {
      log.error("Failed to sync Dify knowledge bases:", error);
      throw error;
    }
  }

  // Get Dify knowledge bases as KnowledgeBase array
  async getDifyKnowledgeBases(
    difyApiBase: string,
    apiKey: string
  ): Promise<KnowledgeBase[]> {
    try {
      const syncResult = await this.syncDifyKnowledgeBases(difyApiBase, apiKey);

      if (!syncResult.indices_info || syncResult.indices_info.length === 0) {
        return [];
      }

      // Transform to KnowledgeBase format
      const difyKnowledgeBases: KnowledgeBase[] = syncResult.indices_info.map(
        (indexInfo: any) => {
          const stats = indexInfo.stats?.base_info || {};
          return {
            id: indexInfo.name,
            name: indexInfo.display_name || indexInfo.name,
            display_name: indexInfo.display_name || indexInfo.name,
            description: "Dify knowledge base",
            documentCount: stats.doc_count || 0,
            chunkCount: stats.chunk_count || 0,
            createdAt: stats.creation_date || null,
            updatedAt: stats.update_date || stats.creation_date || null,
            embeddingModel: stats.embedding_model || "unknown",
            knowledge_sources: "dify",
            ingroup_permission: "",
            group_ids: [],
            store_size: stats.store_size || "",
            process_source: stats.process_source || "Dify",
            avatar: "",
            chunkNum: 0,
            language: "",
            nickname: "",
            parserId: "",
            permission: "",
            tokenNum: 0,
            source: "dify",
            tenant_id: "",
          };
        }
      );

      return difyKnowledgeBases;
    } catch (error) {
      log.error("Failed to get Dify knowledge bases:", error);
      throw error;
    }
  }

  // Sync DataMate knowledge bases and create local records
  async syncDataMateAndCreateRecords(datamateUrl?: string): Promise<{
    indices: string[];
    count: number;
    indices_info: any[];
    created_records: any[];
  }> {
    try {
      const body = datamateUrl
        ? JSON.stringify({ datamate_url: datamateUrl })
        : undefined;

      const response = await fetch(
        API_ENDPOINTS.datamate.syncDatamateKnowledges,
        {
          method: "POST",
          headers: getAuthHeaders(),
          ...(body && { body }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail ||
            "Failed to sync DataMate knowledge bases and create records"
        );
      }

      return data;
    } catch (error) {
      log.error(
        "Failed to sync DataMate knowledge bases and create records:",
        error
      );
      throw error;
    }
  }

  /**
   * Test connection to DataMate server
   * @param datamateUrl Optional DataMate URL to test (uses configured URL if not provided)
   * @returns Promise<{success: boolean, error?: string}>
   */
  async testDataMateConnection(
    datamateUrl?: string
  ): Promise<{ success: boolean; error?: string }> {
    try {
      const body = datamateUrl
        ? JSON.stringify({ datamate_url: datamateUrl })
        : undefined;

      const response = await fetch(API_ENDPOINTS.datamate.testConnection, {
        method: "POST",
        headers: getAuthHeaders(),
        ...(body && { body }),
      });

      if (response.ok) {
        return { success: true };
      }

      const errorData = await response.json();
      return {
        success: false,
        error: errorData.detail || "Connection failed",
      };
    } catch (error) {
      log.error("Failed to test DataMate connection:", error);
      return {
        success: false,
        error:
          error instanceof Error ? error.message : "Connection test failed",
      };
    }
  }

  // Sync Dify knowledge bases
  async syncDifyDatasets(
    difyApiBase: string,
    apiKey: string
  ): Promise<{
    indices: string[];
    count: number;
    indices_info: any[];
  }> {
    try {
      // Normalize URL by removing trailing slash
      const normalizedApiBase = difyApiBase.replace(/\/+$/, "");
      const url = `${normalizedApiBase}/v1/datasets`;

      const response = await fetch(url, {
        method: "GET",
        headers: {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
      });

      if (!response.ok) {
        throw new Error(`Dify API error: ${response.status}`);
      }

      const result = await response.json();
      const datasetsData = result.data || [];

      // Transform to internal format
      const indices: string[] = [];
      const indices_info: any[] = [];

      for (const dataset of datasetsData) {
        const datasetId = dataset.id;
        if (!datasetId) continue;

        indices.push(datasetId);

        indices_info.push({
          name: datasetId,
          display_name: dataset.name,
          stats: {
            base_info: {
              doc_count: dataset.document_count || 0,
              chunk_count: 0,
              store_size: "",
              process_source: "Dify",
              embedding_model: dataset.embedding_model || "",
              embedding_dim: 0,
              creation_date: (dataset.created_at || 0) * 1000,
              update_date: (dataset.updated_at || 0) * 1000,
            },
            search_performance: {
              total_search_count: 0,
              hit_count: 0,
            },
          },
        });
      }

      return {
        indices,
        count: indices.length,
        indices_info,
      };
    } catch (error) {
      log.error("Failed to sync Dify datasets:", error);
      throw error;
    }
  }

  // Get knowledge bases with stats from all sources (very slow, don't use it)
  async getKnowledgeBasesInfo(
    skipHealthCheck = false,
    includeDataMateSync = true,
    tenantId: string | null = null
  ): Promise<KnowledgeBasesWithDataMateStatus> {
    try {
      const knowledgeBases: KnowledgeBase[] = [];
      let dataMateSyncError: string | undefined;

      // Get knowledge bases from Elasticsearch
      try {
        // First check Elasticsearch health (unless skipped)
        if (!skipHealthCheck) {
          const isElasticsearchHealthy = await this.checkHealth();
          if (!isElasticsearchHealthy) {
            log.warn("Elasticsearch service unavailable");
          } else {
            // Build URL with tenant_id parameter for filtering
            const url = new URL(
              `${API_ENDPOINTS.knowledgeBase.indices}?include_stats=true`,
              window.location.origin
            );
            if (tenantId) {
              url.searchParams.set("tenant_id", tenantId);
            }
            const response = await fetch(url.toString(), {
              headers: getAuthHeaders(),
            });
            const data = await response.json();

            log.log("Elasticsearch indices response:", data);

            if (data.indices && data.indices_info) {
              log.log(
                "Processing indices_info:",
                data.indices_info.length,
                "items"
              );
              // Convert Elasticsearch indices to knowledge base format
              const esKnowledgeBases = data.indices_info.map(
                (indexInfo: any) => {
                  const stats = indexInfo.stats?.base_info || {};
                  // Backend returns:
                  // - name: internal index_name
                  // - display_name: user-facing knowledge_name (fallback to index_name)
                  // - update_time: timestamp from database for sorting
                  const kbId = indexInfo.name;
                  const kbName = indexInfo.display_name || indexInfo.name;

                  return {
                    id: kbId,
                    name: kbName,
                    display_name: indexInfo.display_name || indexInfo.name,
                    description: "Elasticsearch index",
                    documentCount: stats.doc_count || 0,
                    chunkCount: stats.chunk_count || 0,
                    createdAt: stats.creation_date || null,
                    // Use update_time from database for sorting, fallback to ES update_date
                    updatedAt:
                      indexInfo.update_time ||
                      stats.update_date ||
                      stats.creation_date ||
                      null,
                    embeddingModel: stats.embedding_model || "unknown",
                    knowledge_sources:
                      indexInfo.knowledge_sources || "elasticsearch",
                    ingroup_permission: indexInfo.ingroup_permission || "",
                    group_ids: indexInfo.group_ids || [],
                    store_size: stats.store_size || "",
                    process_source: stats.process_source || "",
                    avatar: "",
                    chunkNum: 0,
                    language: "",
                    nickname: "",
                    parserId: "",
                    permission: indexInfo.permission || "",
                    tokenNum: 0,
                    source: "nexent",
                    tenant_id: indexInfo.tenant_id,
                  };
                }
              );
              log.log("Converted knowledge bases:", esKnowledgeBases);
              knowledgeBases.push(...esKnowledgeBases);
            } else {
              log.log(
                "Skipping indices processing:",
                "indices exists:",
                !!data.indices,
                "indices_info exists:",
                !!data.indices_info,
                "indices length:",
                data.indices?.length,
                "indices_info length:",
                data.indices_info?.length
              );
            }
          }
        }
      } catch (error) {
        log.error("Failed to get Elasticsearch indices:", error);
      }

      // Sync DataMate knowledge bases and get the synced data (only if enabled and URL is configured)
      if (includeDataMateSync) {
        // Check if DataMate URL is configured before attempting sync
        const config = configStore.getConfig();
        const currentDataMateUrl = config.app?.datamateUrl;

        if (!currentDataMateUrl || currentDataMateUrl.trim() === "") {
          // Skip DataMate sync if URL is not configured
          log.info(
            "DataMate URL not configured, skipping DataMate knowledge base sync"
          );
        } else {
          try {
            const syncResult = await this.syncDataMateAndCreateRecords();
            if (syncResult.indices_info) {
              // Convert synced DataMate indices to knowledge base format
              const datamateKnowledgeBases: KnowledgeBase[] =
                syncResult.indices_info.map((indexInfo: any) => {
                  const stats = indexInfo.stats?.base_info || {};
                  const kbId = indexInfo.name;
                  const kbName = indexInfo.display_name || indexInfo.name;

                  return {
                    id: kbId,
                    name: kbName,
                    display_name: indexInfo.display_name || indexInfo.name,
                    description: "DataMate knowledge base",
                    documentCount: stats.doc_count || 0,
                    chunkCount: stats.chunk_count || 0,
                    createdAt: stats.creation_date || null,
                    updatedAt: stats.update_date || stats.creation_date || null,
                    embeddingModel: stats.embedding_model || "unknown",
                    knowledge_sources:
                      indexInfo.knowledge_sources || "datamate",
                    ingroup_permission: indexInfo.ingroup_permission || "",
                    group_ids: indexInfo.group_ids || [],
                    store_size: stats.store_size || "",
                    process_source: stats.process_source || "",
                    avatar: "",
                    chunkNum: 0,
                    language: "",
                    nickname: "",
                    parserId: "",
                    permission: indexInfo.permission || "",
                    tokenNum: 0,
                    source: "datamate",
                    tenant_id: indexInfo.tenant_id,
                  };
                });
              knowledgeBases.push(...datamateKnowledgeBases);
            }
          } catch (error) {
            // Store the error message for DataMate sync failure
            const errorMessage =
              error instanceof Error ? error.message : String(error);
            dataMateSyncError = errorMessage;
            log.error("Failed to sync DataMate knowledge bases:", error);
          }
        }
      }

      return {
        knowledgeBases,
        dataMateSyncError,
      };
    } catch (error) {
      log.error("Failed to get knowledge base list:", error);
      throw error;
    }
  }

  async getKnowledgeBases(skipHealthCheck = false): Promise<string[]> {
    try {
      // First check Elasticsearch health (unless skipped)
      if (!skipHealthCheck) {
        const isElasticsearchHealthy = await this.checkHealth();
        if (!isElasticsearchHealthy) {
          log.warn("Elasticsearch service unavailable");
          return [];
        }
      }

      let knowledgeBases = [];

      try {
        const response = await fetch(`${API_ENDPOINTS.knowledgeBase.indices}`, {
          headers: getAuthHeaders(),
        });
        const data = await response.json();
        knowledgeBases = data.indices;
      } catch (error) {
        log.error("Failed to get knowledge base list:", error);
      }

      return knowledgeBases;
    } catch (error) {
      log.error("Failed to get knowledge base list:", error);
      throw error;
    }
  }

  // Check whether the knowledge base name already exists in Elasticsearch
  async checkKnowledgeBaseNameExists(name: string): Promise<boolean> {
    try {
      const knowledgeBases = await this.getKnowledgeBases(true);
      return knowledgeBases.includes(name);
    } catch (error) {
      log.error("Failed to check knowledge base name existence:", error);
      throw error;
    }
  }

  // New method to check knowledge base name against the new endpoint
  async checkKnowledgeBaseName(
    name: string
  ): Promise<{ status: string; action?: string }> {
    try {
      const response = await fetch(API_ENDPOINTS.knowledgeBase.checkName, {
        method: "POST",
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ knowledge_name: name }),
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Server error during name check");
      }
      return await response.json();
    } catch (error) {
      log.error("Failed to check knowledge base name:", error);
      // Return a specific status to indicate a failed check, so UI can handle it.
      return { status: NAME_CHECK_STATUS.CHECK_FAILED };
    }
  }

  // Create a new knowledge base
  async createKnowledgeBase(
    params: KnowledgeBaseCreateParams
  ): Promise<KnowledgeBase> {
    try {
      // First check Elasticsearch health status to avoid subsequent operation failures
      const isHealthy = await this.checkHealth();
      if (!isHealthy) {
        throw new Error(
          "Elasticsearch service unavailable, cannot create knowledge base"
        );
      }

      // Build request body with optional group permission and user groups
      const requestBody: {
        name: string;
        description: string;
        embeddingModel?: string;
        ingroup_permission?: string;
        group_ids?: number[];
      } = {
        name: params.name,
        description: params.description || "",
        embeddingModel: params.embeddingModel || "",
      };

      // Include group permission and user groups if provided
      if (params.ingroup_permission) {
        requestBody.ingroup_permission = params.ingroup_permission;
      }
      if (params.group_ids && params.group_ids.length > 0) {
        requestBody.group_ids = params.group_ids;
      }

      const response = await fetch(
        API_ENDPOINTS.knowledgeBase.indexDetail(params.name),
        {
          method: "POST",
          headers: getAuthHeaders(), // Add user authentication information to obtain the user id
          body: JSON.stringify(requestBody),
        }
      );

      const result = await response.json();
      // Modify judgment logic, backend returns status field instead of success field
      if (result.status !== "success") {
        throw new Error(result.message || "Failed to create knowledge base");
      }

      // Create a full KnowledgeBase object with default values
      return {
        id: result.id || params.name, // Use returned ID or name as ID
        name: params.name,
        description: params.description || null,
        documentCount: 0,
        chunkCount: 0,
        createdAt: new Date().toISOString(),
        embeddingModel: params.embeddingModel || "",
        avatar: "",
        chunkNum: 0,
        language: "",
        nickname: "",
        parserId: "",
        permission: "",
        tokenNum: 0,
        source: params.source || "elasticsearch",
      };
    } catch (error) {
      log.error("Failed to create knowledge base:", error);
      throw error;
    }
  }

  // Delete a knowledge base
  async deleteKnowledgeBase(id: string): Promise<void> {
    try {
      // Use REST-style DELETE request to delete index
      const response = await fetch(
        API_ENDPOINTS.knowledgeBase.indexDetail(id),
        {
          method: "DELETE",
          headers: getAuthHeaders(),
        }
      );

      const result = await response.json();
      if (result.status !== "success") {
        throw new Error(result.message || "Failed to delete knowledge base");
      }
    } catch (error) {
      log.error("Failed to delete knowledge base:", error);
      throw error;
    }
  }

  // Get all files from a knowledge base, regardless of the existence of index
  async getAllFiles(kbId: string, kbSource?: string): Promise<Document[]> {
    try {
      let response: Response;
      let result: any;

      // Determine which API to call based on knowledge base source
      if (kbSource === "datamate") {
        // Call DataMate files API
        response = await fetch(API_ENDPOINTS.datamate.files(kbId), {
          headers: getAuthHeaders(),
        });
        result = await response.json();
      } else {
        // Call Elasticsearch files API (default behavior)
        response = await fetch(API_ENDPOINTS.knowledgeBase.listFiles(kbId), {
          headers: getAuthHeaders(),
        });
        result = await response.json();
      }

      if (result.status !== "success") {
        throw new Error("Failed to get file list");
      }

      if (!result.files || !Array.isArray(result.files)) {
        return [];
      }

      return result.files.map((file: any) => ({
        id: file.path_or_url,
        kb_id: kbId,
        name: file.file,
        type: this.getFileTypeFromName(file.file || file.path_or_url),
        size: file.file_size,
        create_time: file.create_time,
        chunk_num: file.chunk_count ?? 0,
        token_num: 0,
        status: file.status || "UNKNOWN",
        latest_task_id: file.latest_task_id || "",
        error_reason: file.error_reason,
        // Optional ingestion progress metrics (only present for in-progress files)
        processed_chunk_num:
          typeof file.processed_chunk_num === "number"
            ? file.processed_chunk_num
            : null,
        total_chunk_num:
          typeof file.total_chunk_num === "number"
            ? file.total_chunk_num
            : null,
      }));
    } catch (error) {
      log.error("Failed to get all files:", error);
      throw error;
    }
  }

  // Get file type from filename
  private getFileTypeFromName(filename: string): string {
    if (!filename) return FILE_TYPES.UNKNOWN;

    const extension = filename.split(".").pop()?.toLowerCase();
    return (
      EXTENSION_TO_TYPE_MAP[extension as keyof typeof EXTENSION_TO_TYPE_MAP] ||
      FILE_TYPES.UNKNOWN
    );
  }

  // Upload documents to a knowledge base
  async uploadDocuments(
    kbId: string,
    files: File[],
    chunkingStrategy?: string
  ): Promise<void> {
    try {
      // Create FormData object
      const formData = new FormData();
      formData.append("index_name", kbId);
      for (let i = 0; i < files.length; i++) {
        formData.append("file", files[i]);
      }
      // Default destination is now Minio
      formData.append("destination", "minio");
      formData.append("folder", "knowledge_base");

      // If chunking strategy is provided, add it to the request
      if (chunkingStrategy) {
        formData.append("chunking_strategy", chunkingStrategy);
      }

      // 1. Upload files
      const uploadResponse = await fetch(API_ENDPOINTS.knowledgeBase.upload, {
        method: "POST",
        headers: {
          "User-Agent": "AgentFrontEnd/1.0",
        },
        body: formData,
      });

      const uploadResult = await uploadResponse.json();

      if (!uploadResponse.ok) {
        if (uploadResponse.status === 400) {
          throw new Error(
            uploadResult.error || "File upload validation failed"
          );
        }
        throw new Error("File upload failed");
      }

      if (
        !uploadResult.uploaded_file_paths ||
        uploadResult.uploaded_file_paths.length === 0
      ) {
        throw new Error("No files were uploaded successfully.");
      }

      // 2. Trigger data processing
      // Combine uploaded file paths and filenames into the required format
      const filesToProcess = uploadResult.uploaded_file_paths.map(
        (filePath: string, index: number) => ({
          path_or_url: filePath,
          filename: uploadResult.uploaded_filenames[index],
        })
      );

      const processResponse = await fetch(API_ENDPOINTS.knowledgeBase.process, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({
          index_name: kbId,
          files: filesToProcess,
          chunking_strategy: chunkingStrategy,
          destination: "minio",
        }),
      });

      if (!processResponse.ok) {
        const processResult = await processResponse.json();
        // Handle 500 error (data processing service failure)
        if (processResponse.status === 500) {
          const errorMessage = `Data processing service failed: ${
            processResult.error
          }. Files: ${processResult.files.join(", ")}`;
          throw new Error(errorMessage);
        }
        throw new Error(processResult.error || "Data processing failed");
      }

      // Handle successful response (201)
      if (processResponse.status === 201) {
        return;
      }

      throw new Error("Unknown response status during processing");
    } catch (error) {
      log.error("Failed to upload and process files:", error);
      throw error;
    }
  }

  // Delete a document from a knowledge base
  async deleteDocument(docId: string, kbId: string): Promise<void> {
    try {
      // Use REST-style DELETE request to delete document, requires knowledge base ID and document path
      const response = await fetch(
        `${API_ENDPOINTS.knowledgeBase.indexDetail(
          kbId
        )}/documents?path_or_url=${encodeURIComponent(docId)}`,
        {
          method: "DELETE",
          headers: getAuthHeaders(),
        }
      );

      const result = await response.json();
      if (result.status !== "success") {
        throw new Error(result.message || "Failed to delete document");
      }
    } catch (error) {
      log.error("Failed to delete document:", error);
      throw error;
    }
  }

  // Summary index content
  async summaryIndex(
    indexName: string,
    batchSize: number = 1000,
    onProgress?: (text: string) => void,
    modelId?: number
  ): Promise<string> {
    try {
      const baseUrl = API_ENDPOINTS.knowledgeBase.summary(indexName);
      const url = new URL(baseUrl, window.location.origin);
      url.searchParams.set("batch_size", batchSize.toString());
      if (modelId) {
        url.searchParams.set("model_id", modelId.toString());
      }

      const response = await fetch(url.toString(), {
        method: "POST",
        headers: getAuthHeaders(),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      if (!response.body) {
        throw new Error("Response body is null");
      }

      // Handle streaming response
      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let summary = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        // Decode binary data to text
        const chunk = decoder.decode(value, { stream: true });

        // Handle SSE format data
        const lines = chunk.split("\n\n");
        for (const line of lines) {
          if (line.trim().startsWith("data:")) {
            try {
              // Extract JSON data
              const jsonStr = line.substring(line.indexOf("{"));
              const data = JSON.parse(jsonStr);

              if (data.status === "success") {
                // Accumulate message part to summary
                summary += data.message;

                // If progress callback is provided, call it
                if (onProgress) {
                  onProgress(data.message);
                }
              } else if (data.status === "completed") {
                // On completed, check if the accumulated summary is empty
                if (!summary || summary.trim() === "") {
                  // No summary was generated, throw internationalized error
                  const errorMessage = i18n.t(
                    "knowledgeBase.summary.notGenerated"
                  );
                  throw new Error(errorMessage);
                }
                // If there is a final message, append it
                if (data.message && data.message.trim() !== "") {
                  summary += data.message;
                  if (onProgress) {
                    onProgress(data.message);
                  }
                }
              } else if (data.status === "error") {
                throw new Error(data.message);
              }
            } catch (e) {
              log.error("Failed to parse SSE data:", e, line);
            }
          }
        }
      }

      return summary;
    } catch (error) {
      log.error("Error summarizing index:", error);
      throw error;
    }
  }

  // Change knowledge base summary
  async changeSummary(indexName: string, summaryResult: string): Promise<void> {
    try {
      const response = await fetch(
        API_ENDPOINTS.knowledgeBase.changeSummary(indexName),
        {
          method: "POST",
          headers: getAuthHeaders(),
          body: JSON.stringify({
            summary_result: summaryResult,
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail ||
            data.message ||
            `HTTP error! status: ${response.status}`
        );
      }

      if (data.status !== "success") {
        throw new Error(data.message || "Failed to change summary");
      }
    } catch (error) {
      log.error("Error changing summary:", error);
      if (error instanceof Error) {
        throw error;
      }
      throw new Error("Failed to change summary");
    }
  }

  // Get knowledge base summary
  async getSummary(indexName: string): Promise<string> {
    try {
      const response = await fetch(
        API_ENDPOINTS.knowledgeBase.getSummary(indexName),
        {
          method: "GET",
          headers: getAuthHeaders(),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail ||
            data.message ||
            `HTTP error! status: ${response.status}`
        );
      }

      if (data.status !== "success") {
        throw new Error(data.message || "Failed to get summary");
      }
      return data.summary;
    } catch (error) {
      log.error("Error geting summary:", error);
      if (error instanceof Error) {
        throw error;
      }
      throw new Error("Failed to get summary");
    }
  }

  // Preview chunks from a knowledge base
  async previewChunks(
    indexName: string,
    batchSize: number = 1000
  ): Promise<any[]> {
    try {
      const url = new URL(
        API_ENDPOINTS.knowledgeBase.chunks(indexName),
        window.location.origin
      );
      url.searchParams.set("batch_size", batchSize.toString());

      const response = await fetch(url.toString(), {
        method: "POST",
        headers: getAuthHeaders(),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail ||
            data.message ||
            `HTTP error! status: ${response.status}`
        );
      }

      if (data.status !== "success") {
        throw new Error(data.message || "Failed to get chunks");
      }

      return data.chunks || [];
    } catch (error) {
      log.error("Error getting chunks:", error);
      if (error instanceof Error) {
        throw error;
      }
      throw new Error("Failed to get chunks");
    }
  }

  // Preview chunks from a knowledge base with pagination
  async previewChunksPaginated(
    indexName: string,
    page: number = 1,
    pageSize: number = 10,
    pathOrUrl?: string
  ): Promise<{
    chunks: any[];
    total: number;
    page: number;
    pageSize: number;
  }> {
    try {
      const url = new URL(
        API_ENDPOINTS.knowledgeBase.chunks(indexName),
        window.location.origin
      );
      url.searchParams.set("page", page.toString());
      url.searchParams.set("page_size", pageSize.toString());
      if (pathOrUrl) {
        url.searchParams.set("path_or_url", pathOrUrl);
      }

      const response = await fetch(url.toString(), {
        method: "POST",
        headers: getAuthHeaders(),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail ||
            data.message ||
            `HTTP error! status: ${response.status}`
        );
      }

      if (data.status !== "success") {
        throw new Error(data.message || "Failed to get chunks");
      }

      return {
        chunks: data.chunks || [],
        total: data.total || 0,
        page: data.page || page,
        pageSize: data.page_size || pageSize,
      };
    } catch (error) {
      log.error("Error getting chunks with pagination:", error);
      if (error instanceof Error) {
        throw error;
      }
      throw new Error("Failed to get chunks");
    }
  }

  async createChunk(
    indexName: string,
    payload: {
      content: string;
      filename?: string;
      path_or_url: string;
      metadata?: Record<string, unknown>;
    }
  ): Promise<{ chunk_id: string }> {
    try {
      const response = await fetch(
        API_ENDPOINTS.knowledgeBase.chunk(indexName),
        {
          method: "POST",
          headers: getAuthHeaders(),
          body: JSON.stringify(payload),
        }
      );
      const data = await response.json();

      if (data.status !== "success") {
        throw new Error(data.message || "Failed to create chunk");
      }

      return { chunk_id: data.chunk_id };
    } catch (error) {
      log.error("Error creating chunk:", error);
      if (error instanceof Error) {
        throw error;
      }
      throw new Error("Failed to create chunk");
    }
  }

  async updateChunk(
    indexName: string,
    chunkId: string,
    payload: {
      content?: string;
      filename?: string;
      metadata?: Record<string, unknown>;
    }
  ): Promise<void> {
    try {
      const response = await fetch(
        API_ENDPOINTS.knowledgeBase.chunkDetail(indexName, chunkId),
        {
          method: "PUT",
          headers: getAuthHeaders(),
          body: JSON.stringify(payload),
        }
      );
      const data = await response.json();

      if (data.status !== "success") {
        throw new Error(data.message || "Failed to update chunk");
      }
    } catch (error) {
      log.error("Error updating chunk:", error);
      if (error instanceof Error) {
        throw error;
      }
      throw new Error("Failed to update chunk");
    }
  }

  async deleteChunk(indexName: string, chunkId: string): Promise<void> {
    try {
      const response = await fetch(
        API_ENDPOINTS.knowledgeBase.chunkDetail(indexName, chunkId),
        {
          method: "DELETE",
          headers: getAuthHeaders(),
        }
      );
      const data = await response.json();

      if (data.status !== "success") {
        throw new Error(data.message || "Failed to delete chunk");
      }
    } catch (error) {
      log.error("Error deleting chunk:", error);
      if (error instanceof Error) {
        throw error;
      }
      throw new Error("Failed to delete chunk");
    }
  }

  // Hybrid search to retrieve chunks via combined semantic and accurate scoring
  async hybridSearch(
    indexName: string,
    query: string,
    options?: { topK?: number; weightAccurate?: number }
  ): Promise<{
    results: any[];
    total?: number;
    query_time_ms?: number;
  }> {
    try {
      const response = await fetch(API_ENDPOINTS.knowledgeBase.searchHybrid, {
        method: "POST",
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query,
          index_names: [indexName],
          top_k: options?.topK ?? 10,
          weight_accurate: options?.weightAccurate ?? 0.5,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail ||
            data.message ||
            `HTTP error! status: ${response.status}`
        );
      }

      return {
        results: Array.isArray(data.results) ? data.results : [],
        total: data.total,
        query_time_ms: data.query_time_ms,
      };
    } catch (error) {
      log.error("Failed to execute hybrid search:", error);
      if (error instanceof Error) {
        throw error;
      }
      throw new Error("Failed to execute hybrid search");
    }
  }

  // Update knowledge base info
  async updateKnowledgeBase(
    indexName: string,
    data: {
      knowledge_name?: string;
      ingroup_permission?: string;
      group_ids?: number[];
    }
  ): Promise<void> {
    try {
      const response = await fetch(
        API_ENDPOINTS.knowledgeBase.updateIndex(indexName),
        {
          method: "PATCH",
          headers: {
            ...getAuthHeaders(),
            "Content-Type": "application/json",
          },
          body: JSON.stringify(data),
        }
      );

      const result = await response.json();

      if (!response.ok) {
        throw new Error(
          result.detail || result.message || "Failed to update knowledge base"
        );
      }
    } catch (error) {
      log.error("Failed to update knowledge base:", error);
      if (error instanceof Error) {
        throw error;
      }
      throw new Error("Failed to update knowledge base");
    }
  }

  // Get document error information for a document
  async getDocumentErrorInfo(
    kbId: string,
    docId: string
  ): Promise<{
    errorCode: string | null;
  }> {
    try {
      const response = await fetch(
        API_ENDPOINTS.knowledgeBase.getErrorInfo(kbId, docId),
        {
          headers: getAuthHeaders(),
        }
      );

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      if (data.status !== "success") {
        throw new Error(data.message || "Failed to get error info");
      }

      const errorCode = (data.error_code && String(data.error_code)) || null;

      return {
        errorCode,
      };
    } catch (error) {
      log.error("Failed to get document error info:", error);
      throw error;
    }
  }
}

// Export a singleton instance
const knowledgeBaseService = new KnowledgeBaseService();
export default knowledgeBaseService;
