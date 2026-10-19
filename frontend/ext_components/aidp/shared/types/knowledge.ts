// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type {
  AidpKnowledgeBaseItem as SharedKnowledgeBaseItem,
  AidpKnowledgeBaseListResponse as SharedKnowledgeBaseListResponse,
} from "@/types/agentConfig";

/** Metadata returned by the AIDP knowledge management pages. */
export interface AidpKnowledgeBaseItem extends Omit<
  SharedKnowledgeBaseItem,
  "document_count" | "chunk_count" | "updated_at" | "created_by"
> {
  created_by?: string | null;
  creator_name?: string | null;
  creator_cas_username?: string | null;
}

export interface AidpKnowledgeBaseListResponse extends Omit<
  SharedKnowledgeBaseListResponse,
  "value"
> {
  value: AidpKnowledgeBaseItem[];
  total_count: number;
  has_more: boolean;
  total_reliable: boolean;
}
