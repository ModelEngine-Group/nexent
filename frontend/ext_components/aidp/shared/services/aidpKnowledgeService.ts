// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { KnowledgeBaseDeletionPreview } from "@/types/knowledgeBase";
/**
 * AIDP Knowledge Base Management Service
 *
 * Wraps the AIDP management backend endpoints.
 * Credentials (server_url, api_key) are read by the backend from environment variables.
 */

import {
  API_ENDPOINTS,
  ApiError,
  fetchWithErrorHandling,
} from "@/services/api";
import type { AidpKnowledgeBaseListResponse } from "@/ext_components/aidp/shared/types/knowledge";
import { getAuthHeaders } from "@/lib/auth";
import log from "@/lib/logger";
import { parseAidpGraphTemplate } from "../utils/parseAidpGraphTemplate";
import type { AidpGraphTemplate } from "@/ext_components/aidp/shared/types/graph";
import { handleSessionExpired } from "@/lib/session";
import { ErrorCode, isSessionExpired } from "@/const/errorCode";
import { parseAidpUploadError } from "@/ext_components/aidp/shared/services/aidpUploadUtils";
import type {
  AidpKbDetail,
  AidpUploadResponse,
  AidpDocumentRemoveResponse,
  AidpUploadTaskListResponse,
  AidpModelListResponse,
  AidpCreateKbPayload,
  AidpSetPermissionPayload,
  AidpSaveSettingsResult,
  AidpUpdateKbPayload,
  AidpFolderTreeResponse,
  AidpFolderOperationResult,
  AidpFileMoveResponse,
  AidpFileRenameResponse,
} from "../types/management";

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
  async previewBoundAgents(
    id: string
  ): Promise<KnowledgeBaseDeletionPreview | null> {
    try {
      const response = await fetchWithErrorHandling(
        API_ENDPOINTS.aidpMgmt.boundAgents(id),
        {
          method: "GET",
          headers: getAuthHeaders(),
        }
      );
      return await response.json();
    } catch (error) {
      log.warn("Knowledge base deletion preview unavailable:", error);
      return null;
    }
  }

  async batchGetKbs(kdsIds: string[]): Promise<{
    value: Array<{
      kds_id: string;
      kds_name: string;
      description: string;
      created_at: string | null;
      resource_status: string;
    }>;
  }> {
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.aidpMgmt.kbBatchRead,
      {
        method: "POST",
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ kds_ids: kdsIds }),
      }
    );
    return response.json();
  }

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

    return result;
  }

  /**
   * Get a single knowledge base detail.
   */
  async getKb(id: string, signal?: AbortSignal): Promise<AidpKbDetail> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.kbDetail(id), {});

    const response = await fetchWithErrorHandling(url, {
      method: "GET",
      headers: getAuthHeaders(),
      signal,
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
   * Delete a knowledge base.
   */
  async deleteKb(id: string): Promise<void> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.kbDetail(id), {});

    await fetchWithErrorHandling(url, {
      method: "DELETE",
      headers: getAuthHeaders(),
    });
  }

  /** Upload one selection as a multipart batch; progress covers the whole body. */
  async uploadDocsWithProgress(
    id: string,
    files: File[],
    onProgress: (loaded: number, total: number) => void,
    signal: AbortSignal,
    options: {
      targetFolder?: string;
      relativePaths?: string[];
    } = {}
  ): Promise<AidpUploadResponse> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.kbDocuments(id), {});
    const formData = new FormData();
    for (const file of files) formData.append("files", file);
    if (options.targetFolder !== undefined) {
      formData.append("target_folder", options.targetFolder);
      const relativePaths =
        options.relativePaths ?? files.map((file) => file.name);
      for (const relativePath of relativePaths) {
        formData.append("relative_paths", relativePath);
      }
    }

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
          const result = JSON.parse(xhr.responseText) as AidpUploadResponse;
          resolve(result);
        } catch (error) {
          log.error("Invalid AIDP upload response:", { id, error });
          reject(
            new ApiError(
              ErrorCode.AIDP_RESPONSE_ERROR,
              "Invalid AIDP upload response"
            )
          );
        }
      };
      xhr.onerror = () => {
        cleanUp();
        log.error("AIDP upload connection failed:", { id });
        reject(
          new ApiError(
            ErrorCode.AIDP_CONNECTION_ERROR,
            "AIDP upload connection failed"
          )
        );
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
    const url = new URL(buildUrl(API_ENDPOINTS.aidpMgmt.models, { app }));
    url.searchParams.set("service", service);
    const response = await fetchWithErrorHandling(url.toString(), {
      method: "GET",
      headers: getAuthHeaders(),
    });
    return response.json();
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
   * Update a knowledge base via the partial-update endpoint.
   * Omitted fields are left unchanged on the AIDP side.
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
   * Read one folder level: direct subfolders plus the current folder's
   * server-side paginated files.
   */
  async getFolderTree(
    id: string,
    folderPath: string,
    page: number = 1,
    pageSize: number = 10,
    keyword: string = "",
    includeFiles: boolean = true,
    signal?: AbortSignal
  ): Promise<AidpFolderTreeResponse> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.kbFolderTree(id), {
      folder_path: folderPath,
      page,
      page_size: pageSize,
      include_files: includeFiles ? "true" : "false",
      keyword: keyword.trim() || undefined,
    });
    const response = await fetchWithErrorHandling(url, {
      method: "GET",
      headers: getAuthHeaders(),
      signal,
    });
    const result = await response.json();
    return {
      folder_id:
        typeof result.folder_id === "number" ? result.folder_id : undefined,
      folder_path:
        typeof result.folder_path === "string"
          ? result.folder_path
          : folderPath,
      folders: Array.isArray(result.folders) ? result.folders : [],
      files: {
        page: Number(result.files?.page) || page,
        page_size: Number(result.files?.page_size) || pageSize,
        total: Number(result.files?.total) || 0,
        value: Array.isArray(result.files?.value) ? result.files.value : [],
      },
    };
  }

  async createFolder(
    id: string,
    parentFolder: string,
    folderName: string
  ): Promise<AidpFolderOperationResult> {
    const response = await fetchWithErrorHandling(
      buildUrl(API_ENDPOINTS.aidpMgmt.kbFolders(id), {}),
      {
        method: "POST",
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          parent_folder: parentFolder,
          folder_name: folderName,
        }),
      }
    );
    return response.json();
  }

  async renameFolder(
    id: string,
    parentFolder: string,
    oldFolderName: string,
    newFolderName: string
  ): Promise<AidpFolderOperationResult> {
    const response = await fetchWithErrorHandling(
      buildUrl(API_ENDPOINTS.aidpMgmt.kbFolders(id), {}),
      {
        method: "PATCH",
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          parent_folder: parentFolder,
          old_folder_name: oldFolderName,
          new_folder_name: newFolderName,
        }),
      }
    );
    return response.json();
  }

  /** Delete one folder. AIDP only allows deleting empty folders. */
  async deleteFolder(id: string, folderPath: string): Promise<void> {
    await fetchWithErrorHandling(
      buildUrl(API_ENDPOINTS.aidpMgmt.kbFolders(id), {
        folder_path: folderPath,
      }),
      {
        method: "DELETE",
        headers: getAuthHeaders(),
      }
    );
  }

  async moveFolder(
    id: string,
    parentFolder: string,
    folderName: string,
    targetFolder: string
  ): Promise<AidpFolderOperationResult> {
    const response = await fetchWithErrorHandling(
      buildUrl(API_ENDPOINTS.aidpMgmt.kbFolderMove(id), {}),
      {
        method: "POST",
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          parent_folder: parentFolder,
          folder_name: folderName,
          target_folder: targetFolder,
        }),
      }
    );
    return response.json();
  }

  /** Move files into a folder; AIDP reports per-file outcomes. */
  async moveFiles(
    id: string,
    fileUuids: string[],
    targetFolder: string
  ): Promise<AidpFileMoveResponse> {
    const response = await fetchWithErrorHandling(
      buildUrl(API_ENDPOINTS.aidpMgmt.kbFileMove(id), {}),
      {
        method: "POST",
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          file_uuids: fileUuids,
          target_folder: targetFolder,
        }),
      }
    );
    return response.json();
  }

  async renameFile(
    id: string,
    fileUuid: string,
    newFileName: string
  ): Promise<AidpFileRenameResponse> {
    const response = await fetchWithErrorHandling(
      buildUrl(API_ENDPOINTS.aidpMgmt.kbFiles(id), {}),
      {
        method: "PATCH",
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          file_uuid: fileUuid,
          new_file_name: newFileName,
        }),
      }
    );
    if (response.status === 204) return {};
    const text = await response.text();
    return text ? (JSON.parse(text) as AidpFileRenameResponse) : {};
  }

  /**
   * Read the recent AIDP upload history, separate from the ingested file list.
   */
  async listUploadTasks(
    id: string,
    page: number = 1,
    pageSize: number = 10,
    keyword: string = "",
    status: number = 0,
    signal?: AbortSignal
  ): Promise<AidpUploadTaskListResponse> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.kbUploadTasks(id), {
      page,
      page_size: pageSize,
      keyword,
      status,
    });
    const response = await fetchWithErrorHandling(url, {
      method: "GET",
      headers: getAuthHeaders(),
      signal,
    });
    const result = await response.json();
    return {
      value: Array.isArray(result.value) ? result.value : [],
      total_count: Number(result.total_count) || 0,
      has_more: result.has_more === true,
      total_reliable: result.total_reliable !== false,
      stats: {
        total: Number(result.stats?.total) || 0,
        extracting: Number(result.stats?.extracting) || 0,
        failed: Number(result.stats?.failed) || 0,
        success: Number(result.stats?.success) || 0,
        queued: Number(result.stats?.queued) || 0,
      },
      retention_days: Number(result.retention_days) || 30,
    };
  }

  /**
   * Retry selected failed upload tasks in one request.
   */
  async retryUploadTasks(
    id: string,
    fileUuids: string[]
  ): Promise<AidpDocumentRemoveResponse> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.retryKbUploadTasks(id), {});
    const response = await fetchWithErrorHandling(url, {
      method: "POST",
      headers: {
        ...getAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ file_uuids: fileUuids }),
    });
    return response.json();
  }

  /**
   * Remove one document from an AIDP knowledge base.
   * The AIDP API accepts an array, so the single-document UI sends one item.
   */
  async removeDoc(
    id: string,
    fileUuid: string
  ): Promise<AidpDocumentRemoveResponse> {
    return this.removeDocs(id, [fileUuid]);
  }

  /**
   * Remove multiple documents from an AIDP knowledge base in one request.
   * AIDP reports per-file outcomes via summary/success_list/failed_list.
   */
  async removeDocs(
    id: string,
    fileUuids: string[]
  ): Promise<AidpDocumentRemoveResponse> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.removeKbDocuments(id), {});
    const response = await fetchWithErrorHandling(url, {
      method: "POST",
      headers: {
        ...getAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ file_uuids: fileUuids }),
    });
    return response.json();
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

  /**
   * Build the URL that streams one document for preview.
   *
   * A URL is returned rather than a request because the preview surface loads it
   * directly (fetch, `<img>`, `<a download>`); authentication travels in the
   * HttpOnly cookie, so no authorisation header is needed. AIDP serves the
   * original bytes for docx/xlsx/pptx/pdf/txt and a PDF conversion for every
   * other format, and reports the served name in the `X-File-Name` header the
   * preview reads to pick a renderer.
   */
  getPreviewUrl(id: string, fileUuid: string): string {
    return API_ENDPOINTS.aidpMgmt.previewKbDocument(id, fileUuid);
  }
}

const aidpKnowledgeService = new AidpKnowledgeService();
export default aidpKnowledgeService;
