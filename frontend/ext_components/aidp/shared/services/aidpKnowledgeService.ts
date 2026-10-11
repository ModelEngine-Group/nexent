/**
 * AIDP Knowledge Base Management Service
 *
 * Wraps the AIDP management backend endpoints.
 * Credentials (server_url, api_key) are read by the backend from environment variables.
 */

import { API_ENDPOINTS, fetchWithErrorHandling } from "@/services/api";
import type { AidpKnowledgeBaseListResponse } from "@/ext_components/aidp/shared/types/knowledge";
import { getAuthHeaders } from "@/lib/auth";
import log from "@/lib/logger";
import { parseAidpGraphTemplate } from "../utils/parseAidpGraphTemplate";
import type { AidpGraphTemplate } from "@/ext_components/aidp/shared/types/graph";
import { handleSessionExpired } from "@/lib/session";
import { isSessionExpired } from "@/const/errorCode";
import { parseAidpUploadError } from "@/ext_components/aidp/shared/services/aidpUploadUtils";
import type {
  AidpKbDetail,
  AidpDocumentListResponse,
  AidpUploadSuccessItem,
  AidpUploadFailedItem,
  AidpUploadResponse,
  AidpDocumentOperationItem,
  AidpDocumentRemoveResponse,
  AidpModelListResponse,
  AidpCreateKbPayload,
  AidpSetPermissionPayload,
  AidpSaveSettingsResult,
  AidpUpdateKbPayload,
} from "../types/management";

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
    const url = `${buildUrl(API_ENDPOINTS.aidpMgmt.models, { app })}&service=${encodeURIComponent(service)}`;

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
    pageSize: number = 10,
    keyword: string = "",
    signal?: AbortSignal
  ): Promise<AidpDocumentListResponse> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.kbDocuments(id), {
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
