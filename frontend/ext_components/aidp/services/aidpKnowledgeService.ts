/**
 * AIDP Knowledge Base Management Service
 *
 * Wraps the AIDP management backend endpoints.
 * Credentials (server_url, api_key) are read by the backend from environment variables.
 */

import { API_ENDPOINTS, fetchWithErrorHandling } from "@/services/api";
import type { AidpKnowledgeBaseListResponse } from "@/types/agentConfig";
import { getAuthHeaders } from "@/lib/auth";
import log from "@/lib/logger";
import { parseAidpGraphTemplate } from "@/lib/aidpGraphConfig";
import type { AidpGraphTemplate } from "@/types/aidpGraph";
import { handleSessionExpired } from "@/lib/session";
import { isSessionExpired } from "@/const/errorCode";
import { parseAidpUploadError } from "./aidpUploadUtils";

// ---------- Additional types for AIDP management ----------

export interface AidpKbDetail {
  kds_id: string;
  kds_name: string;
  description?: string;
  document_count?: number;
  chunk_count?: number;
  embedding_model?: string;
  is_multimodal?: boolean;
  caption_enable?: number | null;
  created_at?: string;
  updated_at?: string;
  permission?: "EDIT" | "READ_ONLY" | null;
  ingroup_permission?: "EDIT" | "READ_ONLY" | "PRIVATE";
  group_ids?: number[];
  resource_status?:
    "ACTIVE" | "CREATING" | "DELETE_PENDING" | "ORPHANED" | "UNAVAILABLE";
  /** AIDP personal/enterprise flag in its raw response form. */
  is_private?: boolean | number | string | null;
  /** Personal knowledge base capacity in GB as reported by AIDP. */
  current_cap?: number | null;
  /** Creator display name from AIDP when the response provides one. */
  user_name?: string | null;
  /** False when the reported document count is not a confirmed statistic. */
  document_count_reliable?: boolean;
  chunk_mode?: number | null;
  chunk_token_num?: number | null;
  chunk_overlap_num?: number | null;
  topk?: number | null;
  similarity?: number | null;
  rerank_model?: string | null;
  vlm_model?: string | null;
  llm_model_name?: string | null;
  is_exist_graph?: boolean | null;
  graph_config?: string | Record<string, unknown> | null;
  created_by?: string | null;
  creator_name?: string | null;
}

export interface AidpDocumentItem {
  file_uuid: string;
  file_ino_no: string;
  file_name: string;
  file_size?: number;
  file_type?: string;
  created_at?: string;
  /**
   * Processing status reported by the AIDP file history endpoint:
   * `PROCESSING` | `COMPLETED` | `FAILED` (upper-cased by the backend).
   * Absent when the backend falls back to the completed-files listing, which
   * only ever reports ingested files.
   */
  status?: string | number;
  /** Channel directory the file was ingested from. */
  dir_path?: string;
  error_code?: string | number | null;
  reason?: string | null;
  extraction_failure_reason?: string | null;
  [key: string]: unknown;
}

export interface AidpDocumentListResponse {
  value: AidpDocumentItem[];
  total_count?: number;
  has_more?: boolean;
  /** Whether `total_count` comes from the AIDP Count API (true) or is a
   *  fallback estimate when Count fails (false). When false the frontend
   *  should treat the total as approximate and avoid displaying "共 N 条". */
  total_reliable?: boolean;
  /**
   * Number of files still being processed across the WHOLE knowledge base
   * (not just the returned page). The list polls while this is greater than
   * zero and stops once every file has reached a terminal status.
   */
  processing_count?: number;
}

export interface AidpUploadSuccessItem {
  file_uuid: string;
  file_name: string;
  file_type: string;
  file_size: number;
  file_ino_no: string;
  first_upload_time: number;
}

export interface AidpUploadFailedItem {
  file_name: string;
  reason_zh: string;
  reason_en: string;
  code?: string | number;
}

export interface AidpUploadResponse {
  summary: {
    total: number;
    success: number;
    failed: number;
  };
  success_list: AidpUploadSuccessItem[];
  failed_list: AidpUploadFailedItem[];
}

export interface AidpDocumentOperationItem {
  file_uuid: string;
  code?: string | number;
  error_code?: string | number;
  message?: string;
  reason?: string;
  reason_zh?: string;
  reason_en?: string;
}

export interface AidpDocumentRemoveResponse {
  summary: {
    total: number;
    success: number;
    failed: number;
  };
  success_list: AidpDocumentOperationItem[];
  failed_list: AidpDocumentOperationItem[];
}

type AidpOperationSummary = {
  total: number;
  success: number;
  failed: number;
};

type AidpOperationResponse<TSuccess, TFailure> = {
  summary: AidpOperationSummary;
  success_list: TSuccess[];
  failed_list: TFailure[];
};

const normalizeAidpOperationResponse = <TSuccess, TFailure>(
  result: Partial<AidpOperationResponse<TSuccess, TFailure>>
): AidpOperationResponse<TSuccess, TFailure> => {
  const successList: TSuccess[] = Array.isArray(result.success_list)
    ? result.success_list
    : [];
  const failedList: TFailure[] = Array.isArray(result.failed_list)
    ? result.failed_list
    : [];

  return {
    summary: {
      total:
        typeof result.summary?.total === "number"
          ? result.summary.total
          : successList.length + failedList.length,
      success:
        typeof result.summary?.success === "number"
          ? result.summary.success
          : successList.length,
      failed:
        typeof result.summary?.failed === "number"
          ? result.summary.failed
          : failedList.length,
    },
    success_list: successList,
    failed_list: failedList,
  };
};

export interface AidpModelItem {
  /** Display / identifier used for the model (sent to AIDP as ``vlm_model``). */
  model_name: string;
  display_name?: string;
  model_type?: string;
  /** "llm", "embedding", etc. — informational only on the frontend. */
  service?: string;
  /**
   * Applicability scope: either the string "All", the literal
   * "KnowledgeBase", or an array containing any of those.
   */
  application?: string | string[];
  properties?: {
    description?: string;
    model_type?: string;
    [key: string]: unknown;
  };
  url?: string;
  api_key?: string;
  max_tokens?: number | null;
  temperature?: number | null;
  top_k?: number | null;
  top_p?: number | null;
}

export interface AidpModelListResponse {
  service: string;
  app: string;
  models: AidpModelItem[];
  total_count: number;
}

/**
 * Structured knowledge graph configuration. The backend validates these
 * fields and serializes them into the documented AIDP `graph_config` string,
 * so the frontend never hand-builds the JSON payload.
 */
export interface AidpGraphConfig {
  /** Optional graph extraction LLM model; nested in AIDP graph_config. */
  llm_model_name?: string;
  /** Extraction domain. */
  domain?: "医疗" | "金融" | "常规" | "法律法规";
  /** Sub-graph expansion hop count. */
  retrieve_subgraph_hop?: string;
  /** Inverse of the "enable model thinking" switch. */
  no_think_mode?: "是" | "否";
  /** Extraction prompt language. */
  prompt_language?: "中文" | "英文";
  /** Editable extraction prompt, limited to 4096 characters. */
  prompt_text?: string;
  /** Whether synonym merging is enabled. */
  synonym_merge_enable?: "是" | "否";
  /** Whether semantic disambiguation is enabled. */
  disambiguation_enable?: "是" | "否";
}

export interface AidpCreateKbPayload {
  name: string;
  description?: string;
  embedding_model?: string;
  is_multimodal?: boolean;
  vision_model?: string;
  /** AIDP requires chunk_token_num (int, > 0) and chunk_overlap_num (int, >= 0). */
  chunk_token_num?: number;
  chunk_overlap_num?: number;
  vlm_model?: string;
  is_personal?: number;
  topk?: number;
  similarity?: number;
  smartsplit?: number;
  caption_enable?: number;
  /**
   * Chunking mode: 0 = smart splitting, 1 = legal clauses. Distinct from
   * ``smartsplit``, which stays in place for existing callers.
   */
  chunk_mode?: number;
  /** Whether knowledge graph extraction is enabled for this knowledge base. */
  is_exist_graph?: boolean;
  /**
   * Graph configuration as a structured object. The backend validates it and
   * serializes it into the documented AIDP `graph_config` string.
   */
  graph_config?: AidpGraphConfig;
  /**
   * Nexent-side in-group permission. ``PRIVATE`` forces an empty
   * ``group_ids``; ``READ_ONLY`` / ``EDIT`` require a non-empty group list.
   * Never forwarded to AIDP — the backend writes it to
   * ``aidp_kb_permission_t``.
   */
  ingroup_permission?: "EDIT" | "READ_ONLY" | "PRIVATE";
  /** Group IDs granted the in-group permission. */
  group_ids?: number[];
}

/** Body for PATCH /aidp-mgmt/aidp-permissions/{kds_id}. */
export interface AidpSetPermissionPayload {
  ingroup_permission: "EDIT" | "READ_ONLY" | "PRIVATE";
  group_ids?: number[];
  /** Only include metadata fields when their values have changed. */
  name?: string;
  description?: string;
}

export interface AidpSaveSettingsResult {
  success: boolean;
  permissions_saved: boolean;
  metadata_status: "unchanged" | "updated" | "failed";
  metadata?: AidpKbDetail;
}

export interface AidpUpdateKbPayload {
  name?: string;
  description?: string;
  chunk_mode?: number;
  topk?: number;
}

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
   * List knowledge bases (paginated), optionally filtered by name.
   *
   * `keyword` is forwarded to the backend, which passes it on to AIDP for
   * server-side filtering. A blank keyword is omitted from the query string
   * entirely so an unfiltered call produces the same request as before.
   */
  async listKbs(
    page: number = 1,
    pageSize: number = 10,
    keyword?: string
  ): Promise<AidpKnowledgeBaseListResponse> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.knowledgeBases, {
      page,
      page_size: pageSize,
      keyword: keyword?.trim() || undefined,
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
      next_link: typeof result.next_link === "string" ? result.next_link : null,
      has_more:
        typeof result.has_more === "boolean" ? result.has_more : undefined,
      total_reliable:
        typeof result.total_reliable === "boolean"
          ? result.total_reliable
          : typeof result.total_count === "number",
    };
  }

  /**
   * Count knowledge bases (used as connection test).
   */
  async countKbs(): Promise<{ count: number }> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.kbCount, {});

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
  async getKb(id: string): Promise<AidpKbDetail> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.kbDetail(id), {});

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
  async createKb(payload: AidpCreateKbPayload): Promise<AidpKbDetail> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.knowledgeBases, {});

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
    id: string,
    payload: AidpUpdateKbPayload
  ): Promise<AidpKbDetail> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.kbDetail(id), {});

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
  async deleteKb(id: string): Promise<void> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.kbDetail(id), {});

    await fetchWithErrorHandling(url, {
      method: "DELETE",
      headers: getAuthHeaders(),
    });
  }

  /**
   * Upload documents to a knowledge base (multipart).
   * Keeps multipart encoding and shares error parsing with the XHR transport.
   */
  async uploadDocs(id: string, files: File[]): Promise<AidpUploadResponse> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.kbDocuments(id), {});

    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
    }

    // Strip Content-Type from getAuthHeaders(): when body is FormData,
    // the browser must set "multipart/form-data; boundary=..." itself.
    // getAuthHeaders() hardcodes "application/json" which breaks multipart parsing.
    const requestHeaders = {
      ...(getAuthHeaders() as Record<string, string>),
    };
    delete requestHeaders["Content-Type"];

    const response = await fetch(url, {
      method: "POST",
      headers: requestHeaders,
      body: formData,
    });

    if (!response.ok) {
      const errorText = await response.text();
      log.error("AIDP document upload failed:", errorText);
      const error = parseAidpUploadError(
        response.status,
        response.statusText,
        errorText
      );
      if (
        response.status === 401 ||
        response.status === 499 ||
        isSessionExpired(error.code)
      ) {
        handleSessionExpired();
      }
      throw error;
    }

    const result = (await response.json()) as Partial<AidpUploadResponse>;
    return normalizeAidpOperationResponse<
      AidpUploadSuccessItem,
      AidpUploadFailedItem
    >(result);
  }

  /** Upload one selection as a multipart batch; progress covers the whole body. */
  async uploadDocsWithProgress(
    id: string,
    files: File[],
    onProgress: (loaded: number, total: number) => void,
    signal: AbortSignal
  ): Promise<AidpUploadResponse> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.kbDocuments(id), {});
    const formData = new FormData();
    for (const file of files) formData.append("files", file);

    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const abort = () => xhr.abort();
      const cleanUp = () => signal.removeEventListener("abort", abort);

      if (signal.aborted) {
        reject(new DOMException("Upload aborted", "AbortError"));
        return;
      }

      xhr.open("POST", url);
      xhr.withCredentials = true;
      xhr.setRequestHeader(
        "X-User-Timezone",
        Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"
      );
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress(event.loaded, event.total);
      };
      xhr.upload.onload = () => onProgress(1, 1);
      xhr.onload = () => {
        cleanUp();
        if (xhr.status < 200 || xhr.status >= 300) {
          const errorText = xhr.responseText || "";
          log.error("AIDP document upload failed:", errorText);
          const error = parseAidpUploadError(
            xhr.status,
            xhr.statusText,
            errorText
          );
          if (
            xhr.status === 401 ||
            xhr.status === 499 ||
            isSessionExpired(error.code)
          ) {
            handleSessionExpired();
          }
          reject(error);
          return;
        }

        try {
          const result = JSON.parse(
            xhr.responseText
          ) as Partial<AidpUploadResponse>;
          resolve(
            normalizeAidpOperationResponse<
              AidpUploadSuccessItem,
              AidpUploadFailedItem
            >(result)
          );
        } catch (error) {
          reject(
            error instanceof Error
              ? error
              : new Error("Invalid upload response")
          );
        }
      };
      xhr.onerror = () => {
        cleanUp();
        reject(new Error("Network error while uploading document"));
      };
      xhr.onabort = () => {
        cleanUp();
        reject(new DOMException("Upload aborted", "AbortError"));
      };
      signal.addEventListener("abort", abort, { once: true });
      xhr.send(formData);
    });
  }

  /**
   * List available models from AIDP ModelService (filtered server-side to
   * models applicable to the given ``app``).
   */
  async listModels(
    service: string = "llm",
    app: string = "KnowledgeBase"
  ): Promise<AidpModelListResponse> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.models, { service, app });

    const response = await fetchWithErrorHandling(url, {
      method: "GET",
      headers: getAuthHeaders(),
    });
    const result = await response.json();

    return {
      service: typeof result.service === "string" ? result.service : service,
      app: typeof result.app === "string" ? result.app : app,
      models: Array.isArray(result.models) ? result.models : [],
      total_count:
        typeof result.total_count === "number"
          ? result.total_count
          : Array.isArray(result.models)
            ? result.models.length
            : 0,
    };
  }

  async graphTemplate(
    language: "chinese" | "english"
  ): Promise<AidpGraphTemplate> {
    const response = await fetchWithErrorHandling(
      buildUrl(API_ENDPOINTS.aidpMgmt.graphTemplate, { language }),
      { method: "GET", headers: getAuthHeaders() }
    );
    return parseAidpGraphTemplate(await response.json());
  }

  /**
   * Save local permissions first, then synchronize supplied metadata changes.
   */
  async setPermission(
    id: string,
    payload: AidpSetPermissionPayload
  ): Promise<AidpSaveSettingsResult> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.kbPermission(id), {});

    const response = await fetchWithErrorHandling(url, {
      method: "PATCH",
      headers: {
        ...getAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    return response.json();
  }

  /**
   * List documents for a knowledge base.
   */
  async listDocs(
    id: string,
    page: number = 1,
    pageSize: number = 10
  ): Promise<AidpDocumentListResponse> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.kbDocuments(id), {
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
          : typeof result.total_count === "number",
      processing_count:
        typeof result.processing_count === "number"
          ? result.processing_count
          : undefined,
    };
  }

  async listIngestedFiles(
    id: string,
    page: number = 1,
    pageSize: number = 10,
    keyword: string = "",
    signal?: AbortSignal
  ): Promise<AidpDocumentListResponse> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.kbFiles(id), {
      page,
      page_size: pageSize,
      keyword,
    });
    const response = await fetchWithErrorHandling(url, {
      method: "GET",
      headers: getAuthHeaders(),
      signal,
    });
    const result = await response.json();
    return {
      value: Array.isArray(result.value) ? result.value : [],
      total_count:
        typeof result.total_count === "number" ? result.total_count : undefined,
      has_more:
        typeof result.has_more === "boolean" ? result.has_more : undefined,
      total_reliable: result.total_reliable !== false,
      processing_count: 0,
    };
  }

  /**
   * Remove one document from an AIDP knowledge base.
   * The AIDP API accepts an array, so the single-document UI sends one item.
   */
  async removeDoc(
    id: string,
    fileUuid: string
  ): Promise<AidpDocumentRemoveResponse> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.removeKbDocuments(id), {});
    const response = await fetchWithErrorHandling(url, {
      method: "POST",
      headers: {
        ...getAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ file_uuids: [fileUuid] }),
    });
    const result =
      (await response.json()) as Partial<AidpDocumentRemoveResponse>;
    return normalizeAidpOperationResponse<
      AidpDocumentOperationItem,
      AidpDocumentOperationItem
    >(result);
  }

  /**
   * Download one document through the AIDP management backend.
   */
  async downloadDoc(id: string, fileUuid: string): Promise<Response> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.downloadKbDocument(id), {});
    return fetchWithErrorHandling(url, {
      method: "POST",
      headers: {
        ...getAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ file_uuid: fileUuid }),
    });
  }
}

const aidpKnowledgeService = new AidpKnowledgeService();
export default aidpKnowledgeService;
