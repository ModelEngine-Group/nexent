/**
 * AIDP Knowledge Base Management Service
 *
 * Wraps the 8 AIDP management backend endpoints.
 * Credentials (server_url, api_key) are passed per-call from localStorage.
 */

import { API_ENDPOINTS, fetchWithErrorHandling } from "./api";
import type {
  AidpKnowledgeBaseItem,
  AidpKnowledgeBaseListResponse,
} from "@/types/agentConfig";
import { getAuthHeaders } from "@/lib/auth";
import log from "@/lib/logger";

// ---------- Additional types for AIDP management ----------

export interface AidpKbDetail {
  kds_id: string;
  kds_name: string;
  description?: string;
  document_count?: number;
  chunk_count?: number;
  embedding_model?: string;
  is_multimodal?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface AidpDocumentItem {
  file_ino_no: string;
  file_name: string;
  file_size?: number;
  file_type?: string;
  created_at?: string;
}

export interface AidpDocumentListResponse {
  value: AidpDocumentItem[];
  total_count?: number;
  has_more?: boolean;
  /** Whether `total_count` comes from the AIDP Count API (true) or is a
   *  fallback estimate when Count fails (false). When false the frontend
   *  should treat the total as approximate and avoid displaying "共 N 条". */
  total_reliable?: boolean;
}

export interface AidpCreateKbPayload {
  name: string;
  description?: string;
  embedding_model?: string;
  is_multimodal?: boolean;
  vision_model?: string;
  /**
   * AIDP requires chunk_token_num (string, > 0) and chunk_overlap_num (string, >= 0).
   * Aligned with sdk/nexent/core/knowledge_base/mapper.py#build_create_payload defaults.
   */
  chunk_token_num?: string;
  chunk_overlap_num?: string;
  vlm_model?: string;
  is_personal?: string;
  topk?: number;
  similarity?: number;
  smartsplit?: number;
  caption_enable?: number;
}

export interface AidpUpdateKbPayload {
  name?: string;
  description?: string;
}

// ---------- Helper: build URL with query params ----------

function buildUrl(
  base: string,
  params: Record<string, string | number | undefined>
): string {
  const url = new URL(base, globalThis.location.origin);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

// ---------- Service class ----------

class AidpKnowledgeService {
  /**
   * List knowledge bases (paginated).
   */
  async listKbs(
    serverUrl: string,
    apiKey: string,
    page: number = 1,
    pageSize: number = 10
  ): Promise<AidpKnowledgeBaseListResponse> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.knowledgeBases, {
      server_url: serverUrl,
      api_key: apiKey,
      page,
      page_size: pageSize,
    });

    const response = await fetchWithErrorHandling(url, {
      method: "GET",
      headers: getAuthHeaders(),
    });
    const result = await response.json();

    return {
      value: Array.isArray(result.value) ? result.value : [],
      total_count:
        typeof result.total_count === "number" ? result.total_count : undefined,
      next_link:
        typeof result.next_link === "string" ? result.next_link : null,
      has_more:
        typeof result.has_more === "boolean" ? result.has_more : undefined,
      total_reliable:
        typeof result.total_reliable === "boolean"
          ? result.total_reliable
          : (typeof result.total_count === "number"),
    };
  }

  /**
   * Count knowledge bases (used as connection test).
   */
  async countKbs(
    serverUrl: string,
    apiKey: string
  ): Promise<{ count: number }> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.kbCount, {
      server_url: serverUrl,
      api_key: apiKey,
    });

    const response = await fetchWithErrorHandling(url, {
      method: "GET",
      headers: getAuthHeaders(),
    });
    const result = await response.json();

    return {
      count:
        typeof result.total_count === "number"
          ? result.total_count
          : typeof result.count === "number"
            ? result.count
            : 0,
    };
  }

  /**
   * Get a single knowledge base detail.
   */
  async getKb(
    serverUrl: string,
    apiKey: string,
    id: string
  ): Promise<AidpKbDetail> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.kbDetail(id), {
      server_url: serverUrl,
      api_key: apiKey,
    });

    const response = await fetchWithErrorHandling(url, {
      method: "GET",
      headers: getAuthHeaders(),
    });
    const result = await response.json();

    return result as AidpKbDetail;
  }

  /**
   * Create a knowledge base.
   */
  async createKb(
    serverUrl: string,
    apiKey: string,
    payload: AidpCreateKbPayload
  ): Promise<AidpKbDetail> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.knowledgeBases, {
      server_url: serverUrl,
      api_key: apiKey,
    });

    const response = await fetchWithErrorHandling(url, {
      method: "POST",
      headers: {
        ...getAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    const result = await response.json();

    return result as AidpKbDetail;
  }

  /**
   * Update a knowledge base (name / description only).
   */
  async updateKb(
    serverUrl: string,
    apiKey: string,
    id: string,
    payload: AidpUpdateKbPayload
  ): Promise<AidpKbDetail> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.kbDetail(id), {
      server_url: serverUrl,
      api_key: apiKey,
    });

    const response = await fetchWithErrorHandling(url, {
      method: "PUT",
      headers: {
        ...getAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    const result = await response.json();

    return result as AidpKbDetail;
  }

  /**
   * Delete a knowledge base.
   */
  async deleteKb(
    serverUrl: string,
    apiKey: string,
    id: string
  ): Promise<void> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.kbDetail(id), {
      server_url: serverUrl,
      api_key: apiKey,
    });

    await fetchWithErrorHandling(url, {
      method: "DELETE",
      headers: getAuthHeaders(),
    });
  }

  /**
   * Upload documents to a knowledge base (multipart).
   * Bypasses fetchWithErrorHandling since it expects JSON.
   */
  async uploadDocs(
    serverUrl: string,
    apiKey: string,
    id: string,
    files: File[]
  ): Promise<{ success: number; failed: number; errors: string[] }> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.kbDocuments(id), {
      server_url: serverUrl,
      api_key: apiKey,
    });

    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
    }

    // Strip Content-Type from getAuthHeaders(): when body is FormData,
    // the browser must set "multipart/form-data; boundary=..." itself.
    // getAuthHeaders() hardcodes "application/json" which breaks multipart parsing.
    const { "Content-Type": _ignored, ...restHeaders } = getAuthHeaders() as Record<string, string>;

    const response = await fetch(url, {
      method: "POST",
      headers: restHeaders,
      body: formData,
    });

    if (!response.ok) {
      const errorText = await response.text();
      log.error("AIDP document upload failed:", errorText);
      throw new Error(
        `Upload failed (${response.status}): ${errorText || response.statusText}`
      );
    }

    const result = await response.json();

    return {
      success:
        typeof result.success_count === "number"
          ? result.success_count
          : files.length,
      failed:
        typeof result.failed_count === "number" ? result.failed_count : 0,
      errors: Array.isArray(result.errors) ? result.errors : [],
    };
  }

  /**
   * List documents for a knowledge base.
   */
  async listDocs(
    serverUrl: string,
    apiKey: string,
    id: string,
    page: number = 1,
    pageSize: number = 10
  ): Promise<AidpDocumentListResponse> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.kbDocuments(id), {
      server_url: serverUrl,
      api_key: apiKey,
      page,
      page_size: pageSize,
    });

    const response = await fetchWithErrorHandling(url, {
      method: "GET",
      headers: getAuthHeaders(),
    });
    const result = await response.json();

    return {
      value: Array.isArray(result.value) ? result.value : [],
      total_count:
        typeof result.total_count === "number" ? result.total_count : undefined,
      has_more:
        typeof result.has_more === "boolean" ? result.has_more : undefined,
      total_reliable:
        typeof result.total_reliable === "boolean"
          ? result.total_reliable
          : (typeof result.total_count === "number"),
    };
  }
}

const aidpKnowledgeService = new AidpKnowledgeService();
export default aidpKnowledgeService;
