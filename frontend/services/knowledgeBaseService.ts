// Unified encapsulation of knowledge base related API calls

import { API_ENDPOINTS } from "./api";

import { NAME_CHECK_STATUS } from "@/const/agentConfig";
import { FILE_TYPES, EXTENSION_TO_TYPE_MAP } from "@/const/knowledgeBase";
import {
  Document,
  KnowledgeBase,
  KnowledgeBaseCreateParams,
} from "@/types/knowledgeBase";
import { getAuthHeaders, fetchWithAuth } from "@/lib/auth";
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

  // Get knowledge bases with stats (very slow, don't use it)
  async getKnowledgeBasesInfo(
    skipHealthCheck = false
  ): Promise<KnowledgeBase[]> {
    try {
      // First check Elasticsearch health (unless skipped)
      if (!skipHealthCheck) {
        const isElasticsearchHealthy = await this.checkHealth();
        if (!isElasticsearchHealthy) {
          log.warn("Elasticsearch service unavailable");
          return [];
        }
      }

      let knowledgeBases: KnowledgeBase[] = [];

      // Get knowledge bases from Elasticsearch
      try {
        const response = await fetch(
          `${API_ENDPOINTS.knowledgeBase.indices}?include_stats=true`,
          {
            headers: getAuthHeaders(),
          }
        );
        const data = await response.json();

        if (data.indices && data.indices_info) {
          // Convert Elasticsearch indices to knowledge base format
          knowledgeBases = data.indices_info.map((indexInfo: any) => {
            const stats = indexInfo.stats?.base_info || {};

            return {
              id: indexInfo.name,
              name: indexInfo.name,
              description: "Elasticsearch index",
              documentCount: stats.doc_count || 0,
              chunkCount: stats.chunk_count || 0,
              createdAt:
                stats.creation_date || new Date().toISOString().split("T")[0],
              embeddingModel: stats.embedding_model || "unknown",
              avatar: "",
              chunkNum: 0,
              language: "",
              nickname: "",
              parserId: "",
              permission: "",
              tokenNum: 0,
              source: "elasticsearch",
            };
          });
        }
      } catch (error) {
        log.error("Failed to get Elasticsearch indices:", error);
      }

      return knowledgeBases;
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
      const response = await fetch(
        API_ENDPOINTS.knowledgeBase.checkName(name),
        {
          method: "GET",
          headers: getAuthHeaders(),
        }
      );
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

      const response = await fetch(
        API_ENDPOINTS.knowledgeBase.indexDetail(params.name),
        {
          method: "POST",
          headers: getAuthHeaders(), // Add user authentication information to obtain the user id
          body: JSON.stringify({
            name: params.name,
            description: params.description || "",
            embeddingModel: params.embeddingModel || "",
          }),
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
  async getAllFiles(kbId: string): Promise<Document[]> {
    try {
      const response = await fetch(
        API_ENDPOINTS.knowledgeBase.listFiles(kbId),
        {
          headers: getAuthHeaders(),
        }
      );
      const result = await response.json();

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
        chunk_num: file.chunk_count || 0,
        token_num: 0,
        status: file.status || "UNKNOWN",
        latest_task_id: file.latest_task_id || "",
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
}

// Export a singleton instance
const knowledgeBaseService = new KnowledgeBaseService();
export default knowledgeBaseService;
