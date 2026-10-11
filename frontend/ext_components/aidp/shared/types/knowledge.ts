import type {
  AidpKnowledgeBaseItem as SharedKnowledgeBaseItem,
  AidpKnowledgeBaseListResponse as SharedKnowledgeBaseListResponse,
} from "@/types/agentConfig";

/** Metadata returned by the AIDP knowledge management pages. */
export interface AidpKnowledgeBaseItem extends Omit<
  SharedKnowledgeBaseItem,
  "document_count" | "chunk_count"
> {
  document_count?: number | null;
  chunk_count?: number | null;
  creator_name?: string | null;
  document_count_reliable?: boolean;
}

export interface AidpKnowledgeBaseListResponse extends Omit<
  SharedKnowledgeBaseListResponse,
  "value"
> {
  value: AidpKnowledgeBaseItem[];
}
