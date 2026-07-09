/**
 * Higher-level business service for unified KB management.
 *
 * Wraps `unifiedKBService` (the thin HTTP client) with business-oriented
 * methods: adapter filtering, KB CRUD with Q2 permission fallback,
 * standard multipart document upload, and cross-KB retrieval.
 *
 * `unifiedKBService` remains the 1:1 HTTP layer; this service adds
 * scenario-specific logic on top.
 */

import { getAuthHeaders } from "@/lib/auth";
import log from "@/lib/logger";
import unifiedKBService from "@/services/unifiedKBService";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import type {
  AdapterInfo,
  KbSummary,
  DocSummary,
  DocStatus,
  CreateKbConfig,
  UpdateKbConfig,
} from "@/types/unifiedKnowledgeBase";
import type {
  UnifiedAdapter,
  UnifiedAdapterCapabilities,
  UnifiedKnowledgeBase,
  UnifiedDocument,
  UnifiedSearchResponse,
} from "@/types/unifiedKB";

const API_BASE_URL = "/api/v1/kb";

// =============================================================================
// Mapping helpers (unifiedKB types → business types)
// =============================================================================

function toAdapterInfo(a: UnifiedAdapter): AdapterInfo {
  return {
    adapter_id: a.adapter_id,
    platform: a.platform as AdapterInfo["platform"],
    name: a.name,
    status: a.status as AdapterInfo["status"],
    enabled: a.enabled,
    health_status: a.health_status,
    capabilities: a.capabilities,
    created_at: a.create_time,
    updated_at: a.update_time,
  };
}

function toKbSummary(
  kb: UnifiedKnowledgeBase,
  adapterId: number,
  adapterPlatform: string,
): KbSummary {
  return {
    id: kb.knowledge_base_id,
    adapter_id: adapterId,
    adapter_platform: adapterPlatform,
    name: kb.name,
    description: kb.description,
    document_count: kb.document_count,
    chunk_count: kb.chunk_count,
    embedding_model: kb.embedding_model,
    metadata: kb.metadata as Record<string, unknown> | undefined,
  };
}

function toDocSummary(
  doc: UnifiedDocument,
  kbId: string,
  adapterId: number,
): DocSummary {
  return {
    document_id: doc.id,
    knowledge_base_id: kbId,
    adapter_id: adapterId,
    name: doc.name ?? "",
    size: doc.size ?? 0,
    status: (doc.status ?? "indexing") as DocSummary["status"],
    chunk_count: doc.chunk_count,
    error_message: doc.error_message,
    created_at: doc.created_at,
  };
}

// =============================================================================
// Service
// =============================================================================

class UnifiedKnowledgeBaseManager {
  // ===========================================================================
  // Adapter
  // ===========================================================================

  /** List all enabled adapters (disabled ones filtered out). */
  async listAllAdapters(): Promise<AdapterInfo[]> {
    const res = await unifiedKBService.listAdapters(true);
    return res.list.filter((a) => a.enabled).map(toAdapterInfo);
  }

  /** Fetch a single adapter by ID. */
  async getAdapter(id: number): Promise<AdapterInfo> {
    const a = await unifiedKBService.getAdapter(id);
    return toAdapterInfo(a);
  }

  /** Pull live capabilities from the adapter. */
  async getAdapterCapabilities(id: number): Promise<UnifiedAdapterCapabilities> {
    return unifiedKBService.getCapabilities(id);
  }

  /** Run the adapter's health check. */
  async checkAdapterHealth(
    id: number,
  ): Promise<{ status: "ok" | "error"; details?: unknown }> {
    const res = await unifiedKBService.checkHealth(id);
    return { status: res.status, details: res };
  }

  /**
   * List ALL adapters for the management UI.
   * Unlike `listAllAdapters`, this includes disabled adapters so the user
   * can re-enable or inspect them.
   */
  async listAllAdaptersForManagement(): Promise<AdapterInfo[]> {
    const res = await unifiedKBService.listAdapters(false);
    return res.list.map(toAdapterInfo);
  }

  /** Update adapter metadata / enabled state. */
  async updateAdapter(
    id: number,
    updates: { name?: string; enabled?: boolean; external_kb_config?: Record<string, unknown> },
  ): Promise<AdapterInfo> {
    const updated = await unifiedKBService.updateAdapter(id, updates);
    return toAdapterInfo(updated);
  }

  /**
   * Delete an adapter. The backend rejects deletion of the `local` adapter,
   * which will surface as an error to the caller.
   */
  async deleteAdapter(id: number): Promise<void> {
    await unifiedKBService.deleteAdapter(id);
  }

  // ===========================================================================
  // KB CRUD
  // ===========================================================================

  /**
   * Create a KB on the given adapter.
   *
   * For local adapters, if `config` includes `ingroup_permission` or
   * `group_ids`, a follow-up call to the legacy `knowledgeBaseService`
   * patches permissions (Q2 fallback). The fallback is non-fatal.
   */
  async createKb(adapterId: number, config: CreateKbConfig): Promise<KbSummary> {
    const created = await unifiedKBService.createKnowledgeBase(adapterId, {
      name: config.name,
      description: config.description,
      embedding_model_config: config.embedding_model
        ? { model_name: config.embedding_model }
        : undefined,
      extra: {},
    });

    // ★ Q2 fallback: patch permissions via legacy service for local adapter
    const adapter = await unifiedKBService.getAdapter(adapterId);
    if (
      adapter.platform === "local" &&
      (config.ingroup_permission || (config.group_ids?.length ?? 0) > 0)
    ) {
      try {
        await knowledgeBaseService.updateKnowledgeBase(
          created.knowledge_base_id,
          {
            ingroup_permission: config.ingroup_permission,
            group_ids: config.group_ids,
          },
        );
      } catch (permErr) {
        log.warn("Permission update failed (non-fatal):", permErr);
      }
    }

    return toKbSummary(created, adapterId, adapter.platform);
  }

  /** Update KB name / description. */
  async updateKb(
    adapterId: number,
    kbId: string,
    updates: UpdateKbConfig,
  ): Promise<KbSummary> {
    const updated = await unifiedKBService.updateKnowledgeBase(
      adapterId,
      kbId,
      { name: updates.name, description: updates.description },
    );
    const adapter = await unifiedKBService.getAdapter(adapterId);
    return toKbSummary(updated, adapterId, adapter.platform);
  }

  /** Delete a KB and all its documents. */
  async deleteKb(adapterId: number, kbId: string): Promise<void> {
    await unifiedKBService.deleteKnowledgeBase(adapterId, kbId);
  }

  /** List KBs within a single adapter (paginated). */
  async listKbsInAdapter(
    adapterId: number,
    opts?: { keyword?: string; page?: number; pageSize?: number },
  ): Promise<{ kbs: KbSummary[]; total: number; page: number; pageSize: number }> {
    const res = await unifiedKBService.listKnowledgeBases(adapterId, opts);
    const adapter = await unifiedKBService.getAdapter(adapterId);
    return {
      kbs: res.list.map((kb) => toKbSummary(kb, adapterId, adapter.platform)),
      total: res.total,
      page: res.page,
      pageSize: res.page_size,
    };
  }

  /** Aggregate KBs from ALL enabled adapters. */
  async listAllKbs(opts?: { keyword?: string }): Promise<KbSummary[]> {
    const res = await unifiedKBService.listAllKnowledgeBases(opts?.keyword);
    return res.list.map((kb) =>
      toKbSummary(
        kb,
        kb.adapter_id ?? 0,
        kb.platform ?? "unknown",
      ),
    );
  }

  // ===========================================================================
  // Documents
  // ===========================================================================

  /**
   * Upload documents via standard multipart/form-data.
   *
   * Uses FormData directly — the backend's `UploadFile`/`Form(...)` signature
   * only accepts multipart, so this cannot live in the thin HTTP client layer.
   */
  async uploadDocuments(
    adapterId: number,
    kbId: string,
    files: File[],
    opts?: { chunking_strategy?: string; metadata?: object },
  ): Promise<DocSummary[]> {
    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
    }
    formData.append("chunking_strategy", opts?.chunking_strategy ?? "basic");
    if (opts?.metadata) {
      formData.append("metadata", JSON.stringify(opts.metadata));
    }

    const res = await fetch(
      `${API_BASE_URL}/adapters/${adapterId}/knowledge-bases/${kbId}/documents`,
      {
        method: "POST",
        headers: getAuthHeaders(),
        body: formData,
      },
    );

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status}: ${text || res.statusText}`);
    }

    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) {
      const data = (await res.json()) as UnifiedDocument[] | { list: UnifiedDocument[] };
      const items = Array.isArray(data) ? data : (data.list ?? []);
      return items.map((doc) => toDocSummary(doc, kbId, adapterId));
    }
    return [];
  }

  /** List documents in a KB (paginated). */
  async listDocuments(
    adapterId: number,
    kbId: string,
    opts?: { page?: number; pageSize?: number },
  ): Promise<{ docs: DocSummary[]; total: number; page: number; pageSize: number }> {
    const res = await unifiedKBService.listDocuments(adapterId, kbId, opts);
    return {
      docs: res.list.map((doc) => toDocSummary(doc, kbId, adapterId)),
      total: res.total,
      page: res.page,
      pageSize: res.page_size,
    };
  }

  /** Delete a single document. */
  async deleteDocument(
    adapterId: number,
    kbId: string,
    docId: string,
  ): Promise<void> {
    await unifiedKBService.deleteDocument(adapterId, kbId, docId);
  }

  /** Query indexing status for a document. */
  async getDocumentStatus(
    adapterId: number,
    kbId: string,
    docId: string,
  ): Promise<DocStatus> {
    const res = await unifiedKBService.getDocumentStatus(adapterId, kbId, docId);
    return {
      document_id: docId,
      status: res.status as DocStatus["status"],
      chunk_count: res.chunk_count,
      error_message: res.error_message,
    };
  }

  /** Generate a signed download URL for a document. */
  async getDocumentDownloadUrl(
    adapterId: number,
    kbId: string,
    docId: string,
  ): Promise<{ download_url: string; filename?: string; expires_in?: number }> {
    const res = await unifiedKBService.getDocumentDownloadUrl(adapterId, kbId, docId);
    return { download_url: res.download_url, filename: res.filename, expires_in: res.expires_in };
  }

  // ===========================================================================
  // Retrieve
  // ===========================================================================

  /** Search within a single KB. */
  async retrieveInKb(
    adapterId: number,
    kbId: string,
    query: string,
    opts?: {
      top_k?: number;
      search_mode?: string;
      score_threshold?: number;
      rerank?: boolean;
    },
  ): Promise<UnifiedSearchResponse> {
    return unifiedKBService.retrieve(adapterId, kbId, {
      query,
      retrieval_model: {
        search_method: (opts?.search_mode ?? "hybrid_search") as "hybrid_search" | "semantic_search" | "keyword_search",
        top_k: opts?.top_k,
        score_threshold: opts?.score_threshold,
        reranking_enable: opts?.rerank,
      },
    });
  }

  /** Cross-adapter retrieval across multiple KBs. */
  async retrieveAcrossKbs(
    kbRefs: Array<{ adapter_id: number; kb_id: string }>,
    query: string,
    opts?: {
      top_k?: number;
      search_mode?: string;
      score_threshold?: number;
      rerank?: boolean;
    },
  ): Promise<UnifiedSearchResponse> {
    return unifiedKBService.retrieveAll({
      query,
      kb_refs: kbRefs.map((r) => ({
        adapter_id: r.adapter_id,
        knowledge_base_id: r.kb_id,
      })),
      retrieval_model: {
        search_method: (opts?.search_mode ?? "hybrid_search") as "hybrid_search" | "semantic_search" | "keyword_search",
        top_k: opts?.top_k,
        score_threshold: opts?.score_threshold,
        reranking_enable: opts?.rerank,
      },
    });
  }
}

export const unifiedKbManager = new UnifiedKnowledgeBaseManager();
export default unifiedKbManager;
