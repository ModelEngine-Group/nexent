/**
 * Type definitions for the Unified Knowledge Base API.
 * 
 * Covers both local (elasticsearch) and external (Dify/AIDP/...) platforms
 * accessed through the unified API. Single source of truth for KB-related
 * UI interactions.
 */

// =============================================================================
// Adapter
// =============================================================================

export interface UnifiedAdapter {
  adapter_id: number;
  name: string;
  platform: string;            // "local" | "dify" | "aidp" | "datamate" | ...
  status: "running" | "stopped" | "error" | "unknown";
  health_status: "ok" | "error" | "unknown";
  enabled: boolean;
  external_kb_config?: Record<string, unknown>;
  capabilities?: UnifiedAdapterCapabilities;
  last_health_check?: string | null;
  created_by?: string;
  updated_by?: string;
  create_time?: string;
  update_time?: string;
}

export interface UnifiedAdapterCapabilities {
  platform?: string;                // V4: 平台类型（替代旧 adapter_type）
  create_knowledge_base: boolean;
  delete_knowledge_base: boolean;
  update_knowledge_base: boolean;
  upload_document: boolean;
  delete_document: boolean;
  list_documents: boolean;
  query_document_status: boolean;
  download_document: boolean;
  list_models: boolean;
  search_modes: string[];       // "hybrid" | "semantic" | "accurate" | "keyword" | ...
  supports_rerank: boolean;
  supports_multimodal: boolean;
  supports_batch_search: boolean;
  max_kb_ids_per_search: number;
  requires_embedding_model: boolean;
  supports_custom_embedding_model: boolean;
}

// =============================================================================
// Request / Response payloads
// =============================================================================

export interface RegisterAdapterRequest {
  platform: string;
  name?: string;
  external_kb_config?: Record<string, unknown>;
  enabled?: boolean;
  status?: string;
}

export interface UpdateAdapterRequest {
  name?: string;
  external_kb_config?: Record<string, unknown>;
  enabled?: boolean;
  status?: string;
}

export interface CreateKnowledgeBaseRequest {
  name: string;
  description?: string;
  embedding_model_config?: Record<string, unknown>;
  extra?: Record<string, unknown>;
}

export interface UpdateKnowledgeBaseRequest {
  name?: string;
  description?: string;
}

export interface RetrievalModel {
  search_method?: "hybrid_search" | "semantic_search" | "keyword_search";
  top_k?: number;
  score_threshold?: number;
  reranking_enable?: boolean;
}

export interface RetrieveRequest {
  query: string;
  knowledge_base_ids?: string[];
  retrieval_model?: RetrievalModel;
}

export interface KbRef {
  adapter_id: number;
  knowledge_base_id: string;  // 标准字段名，对应旧字段 kb_id
}

export interface RetrieveAllRequest extends RetrieveRequest {
  kb_refs: KbRef[];
}

// =============================================================================
// Knowledge Base (标准字段名)
// =============================================================================

export interface UnifiedKnowledgeBase {
  /** 标准字段名，对应旧字段 kb_id */
  knowledge_base_id: string;
  name: string;
  description?: string;
  document_count: number;
  chunk_count: number;
  embedding_model?: string;
  metadata?: Record<string, unknown>;
  // Enriched fields injected by listAllKnowledgeBasesAcrossAdapters
  adapter_id?: number;
  adapter_name?: string;
  platform?: string;
  source?: "external";
}

// =============================================================================
// Document
// =============================================================================

export interface UnifiedDocument {
  id: string;
  name?: string;
  content?: string;       // Preview snippet
  status?: "indexing" | "completed" | "failed" | "paused";
  chunk_count?: number;
  error_message?: string;
  size?: number;
  type?: string;
  token_count?: number;
  knowledge_base_id?: string;
  created_by?: string;
  created_at?: string;
  updated_at?: string;
}

export interface UnifiedDocumentStatus {
  id: string;
  name: string;
  knowledge_base_id?: string;
  size?: number;
  type?: string;
  status: string;
  chunk_count?: number;
  token_count?: number;
  progress?: number;
  progress_msg?: string;
  error?: string;
  /** @deprecated use `error` instead, kept for backward compat */
  error_message?: string;
  created_at?: string;
  updated_at?: string;
}

export interface UnifiedDocumentDownloadUrl {
  download_url: string;
  filename?: string;
  expires_in?: number;
  expires_at?: string;
}

// =============================================================================
// Search / Retrieve (嵌套结构)
// =============================================================================

export interface SegmentInfo {
  /** 标准：检索片段详细信息 */
  id: string;
  content: string;
  title?: string;
  url?: string;
  filename?: string;
  knowledge_base_id: string;  // 标准字段名，对应旧字段 kb_id
  knowledge_base_name?: string;
  document_id?: string;
  document_name?: string;
  segment_id?: string;
  position?: number;
  tokens?: number;
  keywords?: string[];
  hit_count?: number;
  enabled?: boolean;
  image_url?: string;
  table_data?: Record<string, unknown>;
  score_details?: Record<string, number>;
  metadata?: Record<string, unknown>;
}

export interface SearchRecord {
  /** 标准：检索记录（包含 segment 和 score）*/
  segment: SegmentInfo;
  score: number;
}

/** @deprecated 使用 SearchRecord 代替，保持向后兼容 */
export interface UnifiedSearchResult {
  content: string;
  score: number;
  title: string;
  url?: string;
  filename?: string;
  kb_id: string;  // 旧字段名，对应标准字段 knowledge_base_id
  kb_name?: string;
  document_id?: string;
  segment_id?: string;
  tokens?: number;
  score_details?: Record<string, number>;
  metadata?: Record<string, unknown>;
}

export interface UnifiedSearchResponse {
  records: SearchRecord[];                 // 标准：嵌套结构
  results: UnifiedSearchResult[];          // 向后兼容：扁平结构
  total: number;
  query_time_ms: number;
}

// =============================================================================
// Pagination / list responses
// =============================================================================

export interface PaginatedListResponse<T> {
  list: T[];
  /** @deprecated use `list` instead, kept for backward compat */
  items?: T[];
  total: number;
  page: number;
  page_size: number;
  has_more?: boolean;
}

export interface AdapterListResponse {
  list: UnifiedAdapter[];
  total: number;
}

export interface HealthCheckResponse {
  status: "ok" | "error";
  platform?: string;
  version?: string;
  external_kb_reachable?: boolean;
  message?: string;
}
