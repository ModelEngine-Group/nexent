/**
 * Higher-level business types for the unified KB manager.
 *
 * These wrap the raw HTTP types from `unifiedKB.ts` into shapes
 * convenient for KB management UI scenarios (adapter listing,
 * KB CRUD, document upload, cross-KB retrieval).
 */

import type { UnifiedAdapterCapabilities } from "@/types/unifiedKB";

// Re-export for convenience so consumers can import from one place
export type { UnifiedAdapterCapabilities as AdapterCapabilities } from "@/types/unifiedKB";

// =============================================================================
// Adapter
// =============================================================================

export interface AdapterInfo {
  adapter_id: number;
  platform: "local" | "dify" | "aidp" | "datamate" | "haotian" | "custom";
  name: string;
  status: "running" | "error" | "stopped";
  enabled: boolean;
  health_status?: string;
  capabilities?: UnifiedAdapterCapabilities;
  created_at?: string;
  updated_at?: string;
}

// =============================================================================
// Knowledge Base
// =============================================================================

export interface KbSummary {
  id: string;
  adapter_id: number;
  adapter_platform: string;
  name: string;
  description?: string;
  document_count: number;
  chunk_count: number;
  embedding_model?: string;
  created_at?: string;
  updated_at?: string;
  metadata?: Record<string, unknown>;
}

// =============================================================================
// Document
// =============================================================================

export interface DocSummary {
  document_id: string;
  knowledge_base_id: string;
  adapter_id: number;
  name: string;
  size: number;
  status: "indexing" | "completed" | "failed" | "paused";
  chunk_count?: number;
  error_message?: string;
  created_at?: string;
}

export interface DocStatus {
  document_id: string;
  knowledge_base_id?: string;
  status: "indexing" | "completed" | "failed" | "paused";
  size?: number;
  type?: string;
  token_count?: number;
  progress?: number;
  progress_msg?: string;
  progress_pct?: number;
  chunk_count?: number;
  total_chunks?: number;
  error_message?: string;
  created_at?: string;
  updated_at?: string;
}

// =============================================================================
// Config objects
// =============================================================================

export interface CreateKbConfig {
  name: string;
  description?: string;
  /** Only used for local adapter */
  embedding_model?: string;
  /** Only used for local adapter */
  ingroup_permission?: "EDIT" | "READ_ONLY" | "PRIVATE";
  /** Only used for local adapter */
  group_ids?: number[];
}

export interface UpdateKbConfig {
  name?: string;
  description?: string;
}

export interface RegisterAdapterConfig {
  platform: "dify" | "aidp" | "datamate" | "haotian" | "custom";
  name: string;
  external_kb_config: Record<string, unknown>;
  enabled?: boolean;
}
