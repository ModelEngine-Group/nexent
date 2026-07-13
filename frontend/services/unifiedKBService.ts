/**
 * Unified Knowledge Base Service.
 *
 * Single API client for both local (elasticsearch) and external (Dify/AIDP/...)
 * knowledge bases. All requests go through `/api/v1/kb/...`, which internally
 * dispatches to the correct adapter via ExternalKnowledgeBaseService.
 *
 * This is the standard KB CRUD surface — use it for anything that works
 * uniformly across adapters (list/create/delete KBs, upload/list/delete
 * documents, adapter health & capabilities).
 *
 * `knowledgeBaseService` is NOT deprecated — it is the *local-only extension*
 * service for capabilities that external platforms do not expose
 * (chunk-level CRUD, summary generation, embedding model status, and
 * legacy platform-specific helpers for dify/datamate/idata/aidp that will
 * be retired once those platforms land as registered adapters).
 */

import { getAuthHeaders } from "@/lib/auth";
import log from "@/lib/logger";
import type {
  AdapterListResponse,
  CreateKnowledgeBaseRequest,
  HealthCheckResponse,
  KbRef,
  PaginatedListResponse,
  RegisterAdapterRequest,
  RetrieveAllRequest,
  RetrieveRequest,
  UnifiedAdapter,
  UnifiedAdapterCapabilities,
  UnifiedDocument,
  UnifiedDocumentDownloadUrl,
  UnifiedDocumentStatus,
  UnifiedKnowledgeBase,
  UnifiedSearchResponse,
  UpdateAdapterRequest,
  UpdateKnowledgeBaseRequest,
} from "@/types/unifiedKB";

const API_BASE_URL = "/api/v1/kb";

function buildHeaders(): HeadersInit {
  return getAuthHeaders();
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    log.error(`UnifiedKBService: HTTP ${response.status} — ${text}`);
    throw new Error(`HTTP ${response.status}: ${text || response.statusText}`);
  }
  const ct = response.headers.get("content-type") || "";
  let body: unknown;
  if (ct.includes("application/json")) {
    body = await response.json();
  } else {
    const txt = await response.text();
    body = txt ? JSON.parse(txt) : {};
  }

  // V4 standard envelope unwrap — all /api/v1/kb/* responses are wrapped as
  // {code: 0, data: <payload>, message: "success"} or {code: N, message: "..."}
  if (
    body !== null &&
    typeof body === "object" &&
    !Array.isArray(body) &&
    "code" in body &&
    "data" in body
  ) {
    const env = body as { code: number; data: unknown; message?: string };
    if (env.code !== 0) {
      throw new Error(env.message ?? `API error: code ${env.code}`);
    }
    return env.data as T;
  }

  return body as T;
}

// =============================================================================
// Service
// =============================================================================

class UnifiedKBService {
  // =============================================================================
  // Adapter management
  // =============================================================================

  /**
   * List all adapters registered for the current tenant.
   * Auto-provisions the local adapter if missing.
   */
  async listAdapters(enabledOnly = false): Promise<AdapterListResponse> {
    const qs = enabledOnly ? "?enabled_only=true" : "";
    const res = await fetch(`${API_BASE_URL}/adapters${qs}`, {
      method: "GET",
      headers: buildHeaders(),
    });
    const data = await handleResponse<
      AdapterListResponse | UnifiedAdapter[]
    >(res);
    // Defensive: normalize raw-array responses into `{list, total}` shape.
    if (Array.isArray(data)) {
      return { list: data, total: data.length };
    }
    return data;
  }

  /**
   * Register a new adapter (e.g., dify, aidp).
   */
  async registerAdapter(data: RegisterAdapterRequest): Promise<UnifiedAdapter> {
    const res = await fetch(`${API_BASE_URL}/adapters`, {
      method: "POST",
      headers: buildHeaders(),
      body: JSON.stringify(data),
    });
    return handleResponse<UnifiedAdapter>(res);
  }

  /**
   * Fetch a single adapter by ID (includes credentials & config).
   */
  async getAdapter(adapterId: number): Promise<UnifiedAdapter> {
    const res = await fetch(`${API_BASE_URL}/adapters/${adapterId}`, {
      method: "GET",
      headers: buildHeaders(),
    });
    return handleResponse<UnifiedAdapter>(res);
  }

  /**
   * Update adapter metadata / config. Only fields that are provided are updated.
   */
  async updateAdapter(
    adapterId: number,
    data: UpdateAdapterRequest
  ): Promise<UnifiedAdapter> {
    const res = await fetch(`${API_BASE_URL}/adapters/${adapterId}`, {
      method: "PUT",
      headers: buildHeaders(),
      body: JSON.stringify(data),
    });
    return handleResponse<UnifiedAdapter>(res);
  }

  /**
   * Soft-delete an adapter. Returns `{adapter_id, deleted: true}` on success.
   */
  async deleteAdapter(
    adapterId: number
  ): Promise<{ adapter_id: number; deleted: boolean }> {
    const res = await fetch(`${API_BASE_URL}/adapters/${adapterId}`, {
      method: "DELETE",
      headers: buildHeaders(),
    });
    return handleResponse<{ adapter_id: number; deleted: boolean }>(res);
  }

  /**
   * Run the adapter's health_check and update DB status.
   */
  async checkHealth(adapterId: number): Promise<HealthCheckResponse> {
    const res = await fetch(`${API_BASE_URL}/adapters/${adapterId}/health`, {
      method: "GET",
      headers: buildHeaders(),
    });
    return handleResponse<HealthCheckResponse>(res);
  }

  /**
   * Pull capabilities from the live adapter and persist in DB.
   */
  async getCapabilities(adapterId: number): Promise<UnifiedAdapterCapabilities> {
    const res = await fetch(
      `${API_BASE_URL}/adapters/${adapterId}/capabilities`,
      { method: "GET", headers: buildHeaders() }
    );
    return handleResponse<UnifiedAdapterCapabilities>(res);
  }

  // =============================================================================
  // Knowledge base CRUD
  // =============================================================================

  /**
   * List knowledge bases for a given adapter (paginated).
   */
  async listKnowledgeBases(
    adapterId: number,
    opts: { keyword?: string; page?: number; pageSize?: number } = {}
  ): Promise<PaginatedListResponse<UnifiedKnowledgeBase>> {
    const params = new URLSearchParams();
    if (opts.keyword) params.set("keyword", opts.keyword);
    params.set("page", String(opts.page ?? 1));
    params.set("page_size", String(opts.pageSize ?? 20));
    const res = await fetch(
      `${API_BASE_URL}/adapters/${adapterId}/knowledge-bases?${params}`,
      { method: "GET", headers: buildHeaders() }
    );
    return handleResponse<PaginatedListResponse<UnifiedKnowledgeBase>>(res);
  }

  /**
   * Aggregate KBs from ALL enabled adapters (useful for cross-platform pickers).
   */
  async listAllKnowledgeBases(
    keyword?: string
  ): Promise<{ list: UnifiedKnowledgeBase[]; total: number }> {
    const params = new URLSearchParams();
    if (keyword) params.set("keyword", keyword);
    const res = await fetch(
      `${API_BASE_URL}/knowledge-bases/all?${params}`,
      { method: "GET", headers: buildHeaders() }
    );
    return handleResponse<{ list: UnifiedKnowledgeBase[]; total: number }>(res);
  }

  /**
   * Create a new KB on a given adapter.
   */
  async createKnowledgeBase(
    adapterId: number,
    data: CreateKnowledgeBaseRequest
  ): Promise<UnifiedKnowledgeBase> {
    const res = await fetch(
      `${API_BASE_URL}/adapters/${adapterId}/knowledge-bases`,
      {
        method: "POST",
        headers: buildHeaders(),
        body: JSON.stringify(data),
      }
    );
    return handleResponse<UnifiedKnowledgeBase>(res);
  }

  /**
   * Fetch a single KB by its adapter + KB ID.
   */
  async getKnowledgeBase(
    adapterId: number,
    kbId: string
  ): Promise<UnifiedKnowledgeBase> {
    const res = await fetch(
      `${API_BASE_URL}/adapters/${adapterId}/knowledge-bases/${kbId}`,
      { method: "GET", headers: buildHeaders() }
    );
    return handleResponse<UnifiedKnowledgeBase>(res);
  }

  /**
   * Update KB metadata (name, description).
   */
  async updateKnowledgeBase(
    adapterId: number,
    kbId: string,
    data: UpdateKnowledgeBaseRequest
  ): Promise<UnifiedKnowledgeBase> {
    const res = await fetch(
      `${API_BASE_URL}/adapters/${adapterId}/knowledge-bases/${kbId}`,
      {
        method: "PUT",
        headers: buildHeaders(),
        body: JSON.stringify(data),
      }
    );
    return handleResponse<UnifiedKnowledgeBase>(res);
  }

  /**
   * Delete a KB and all its documents.
   */
  async deleteKnowledgeBase(
    adapterId: number,
    kbId: string
  ): Promise<{ kb_id: string; deleted: boolean }> {
    const res = await fetch(
      `${API_BASE_URL}/adapters/${adapterId}/knowledge-bases/${kbId}`,
      { method: "DELETE", headers: buildHeaders() }
    );
    return handleResponse<{ kb_id: string; deleted: boolean }>(res);
  }

  // =============================================================================
  // Document management
  // =============================================================================

  /**
   * List documents in a KB (paginated).
   */
  async listDocuments(
    adapterId: number,
    kbId: string,
    opts: { page?: number; pageSize?: number } = {}
  ): Promise<PaginatedListResponse<UnifiedDocument>> {
    const params = new URLSearchParams();
    params.set("page", String(opts.page ?? 1));
    params.set("page_size", String(opts.pageSize ?? 20));
    const res = await fetch(
      `${API_BASE_URL}/adapters/${adapterId}/knowledge-bases/${kbId}/documents?${params}`,
      { method: "GET", headers: buildHeaders() }
    );
    return handleResponse<PaginatedListResponse<UnifiedDocument>>(res);
  }

  // uploadDocuments intentionally omitted: backend endpoint requires multipart/form-data
  // (UploadFile/File + Form fields), which JSON.stringify cannot express.
  // Use unifiedKnowledgeBaseService.uploadDocuments() for file uploads.

  /**
   * Delete a single document.
   */
  async deleteDocument(
    adapterId: number,
    kbId: string,
    docId: string
  ): Promise<{ doc_id: string; deleted: boolean }> {
    const res = await fetch(
      `${API_BASE_URL}/adapters/${adapterId}/knowledge-bases/${kbId}/documents/${docId}`,
      { method: "DELETE", headers: buildHeaders() }
    );
    return handleResponse<{ doc_id: string; deleted: boolean }>(res);
  }

  /**
   * Query indexing status / error for a document.
   */
  async getDocumentStatus(
    adapterId: number,
    kbId: string,
    docId: string
  ): Promise<UnifiedDocumentStatus> {
    const res = await fetch(
      `${API_BASE_URL}/adapters/${adapterId}/knowledge-bases/${kbId}/documents/${docId}/status`,
      { method: "GET", headers: buildHeaders() }
    );
    return handleResponse<UnifiedDocumentStatus>(res);
  }

  /**
   * Generate a signed download URL for a document.
   */
  async getDocumentDownloadUrl(
    adapterId: number,
    kbId: string,
    docId: string
  ): Promise<UnifiedDocumentDownloadUrl> {
    const res = await fetch(
      `${API_BASE_URL}/adapters/${adapterId}/knowledge-bases/${kbId}/documents/${docId}/download-url`,
      { method: "GET", headers: buildHeaders() }
    );
    return handleResponse<UnifiedDocumentDownloadUrl>(res);
  }

  // =============================================================================
  // Search / Retrieve
  // =============================================================================

  /**
   * Execute a semantic/hybrid/keyword search inside a single KB.
   *
   * For the local adapter, `search_mode` accepts `hybrid | semantic | accurate`.
   * For external adapters, values pass through (Dify maps `accurate` → `keyword`).
   */
  async retrieve(
    adapterId: number,
    kbId: string,
    data: RetrieveRequest
  ): Promise<UnifiedSearchResponse> {
    const res = await fetch(
      `${API_BASE_URL}/adapters/${adapterId}/knowledge-bases/${kbId}/retrieve`,
      {
        method: "POST",
        headers: buildHeaders(),
        body: JSON.stringify(data),
      }
    );
    return handleResponse<UnifiedSearchResponse>(res);
  }

  /**
   * Execute search across multiple KBs (may span different adapters).
   *
   * `kb_refs` example:
   * ```
   * [{ adapter_id: 1, kb_id: "abc" }, { adapter_id: 2, kb_id: "xyz" }]
   * ```
   *
   * The backend groups calls by adapter, executes them in parallel, and
   * merges + re-ranks results by score.
   */
  async retrieveAll(data: RetrieveAllRequest): Promise<UnifiedSearchResponse> {
    const res = await fetch(`${API_BASE_URL}/retrieve-all`, {
      method: "POST",
      headers: buildHeaders(),
      body: JSON.stringify(data),
    });
    return handleResponse<UnifiedSearchResponse>(res);
  }

  // ---------------------------------------------------------------------------
  // Convenience helpers
  // ---------------------------------------------------------------------------

  /**
   * Build a `kb_refs` array from a list of KnowledgeBase items (which carry
   * `adapter_id` and `knowledge_base_id` after being loaded through `listAllKnowledgeBases`).
   */
  buildKbRefs(items: UnifiedKnowledgeBase[]): KbRef[] {
    return items
      .filter((kb) => typeof kb.adapter_id === "number")
      .map((kb) => ({
        adapter_id: kb.adapter_id as number,
        knowledge_base_id: kb.knowledge_base_id,
      }));
  }

  /**
   * Convert response to a flat result array for consumers that haven't migrated to nested format yet.
   * Extracts `segment` fields from nested `records` structure.
   */
  flattenRecords(response: UnifiedSearchResponse): import("@/types/unifiedKB").UnifiedSearchResult[] {
    // Prefer nested records (standard format), fall back to results (legacy format) for backward compat
    if (response.records && response.records.length > 0) {
      return response.records.map((rec) => ({
        content: rec.segment.content,
        title: rec.segment.title || "",
        url: rec.segment.url,
        filename: rec.segment.filename,
        kb_id: rec.segment.knowledge_base_id,  // 映射标准字段回旧字段名以兼容 consumer
        knowledge_base_name: rec.segment.knowledge_base_name,
        document_id: rec.segment.document_id,
        segment_id: rec.segment.segment_id,
        tokens: rec.segment.tokens,
        score_details: rec.segment.score_details,
        metadata: rec.segment.metadata,
        score: rec.score,
      }));
    }
    return response.results || [];
  }
}

export const unifiedKBService = new UnifiedKBService();
export default unifiedKBService;
