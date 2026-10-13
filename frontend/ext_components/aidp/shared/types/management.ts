export interface AidpKbDetail {
  kds_id: string;
  kds_name: string;
  description?: string;
  document_count?: number | null;
  embedding_model?: string;
  is_multimodal?: boolean;
  caption_enable?: number | null;
  created_at?: string;
  permission?: "EDIT" | "READ_ONLY" | null;
  ingroup_permission?: "EDIT" | "READ_ONLY" | "PRIVATE";
  group_ids?: number[];
  resource_status?:
    "ACTIVE" | "CREATING" | "DELETE_PENDING" | "ORPHANED" | "UNAVAILABLE";
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
  updated_at?: string;
  [key: string]: unknown;
}

export interface AidpDocumentListResponse {
  value: AidpDocumentItem[];
  total_count: number;
  has_more: boolean;
  /** False for search pagination, whose filtered global total is unavailable. */
  total_reliable: boolean;
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
  models: AidpModelItem[];
}

/**
 * Structured knowledge graph configuration. The backend validates these
 * fields and serializes them into the documented AIDP `graph_config` string,
 * so the frontend never hand-builds the JSON payload.
 */
export interface AidpGraphConfig {
  /** Graph extraction LLM model; nested in AIDP graph_config. */
  llm_model_name: string;
  /** Extraction domain. */
  domain: "医疗" | "金融" | "常规" | "法律法规";
  /** Sub-graph expansion hop count. */
  retrieve_subgraph_hop: string;
  /** Inverse of the "enable model thinking" switch. */
  no_think_mode: "是" | "否";
  /** Extraction prompt language. */
  prompt_language: "中文" | "英文";
  /** Editable extraction prompt, limited to 4096 characters. */
  prompt_text: string;
  /** Whether synonym merging is enabled. */
  synonym_merge_enable: "是" | "否";
  /** Whether semantic disambiguation is enabled. */
  disambiguation_enable: "是" | "否";
}

export interface AidpCreateKbPayload {
  name: string;
  description: string;
  embedding_model: string;
  /** AIDP requires chunk_token_num (int, > 0) and chunk_overlap_num (int, >= 0). */
  chunk_token_num?: number;
  chunk_overlap_num?: number;
  vlm_model?: string;
  is_personal?: number;
  topk?: number;
  similarity?: number;
  caption_enable?: number;
  /** Chunking mode: 0 = smart splitting, 1 = legal clauses. */
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
