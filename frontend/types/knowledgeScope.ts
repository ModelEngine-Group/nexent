export type KnowledgeScopeMode = "inherit" | "override" | "disabled";

export interface ConversationKnowledgeScope {
  schema_version: 1;
  local: {
    mode: KnowledgeScopeMode;
    knowledge_ids: string[];
  };
  aidp: {
    mode: KnowledgeScopeMode;
    kds_ids: string[];
  };
}

export interface KnowledgeCapabilities {
  agent_id: number;
  version_no: number;
  sources: {
    local: {
      enabled: boolean;
      max_select: number;
      requires_same_embedding_model: boolean;
      default_summary: string;
    };
    aidp: {
      enabled: boolean;
      max_select: number;
      default_summary: string;
    };
  };
}

export const DEFAULT_CONVERSATION_KNOWLEDGE_SCOPE: ConversationKnowledgeScope =
  {
    schema_version: 1,
    local: { mode: "inherit", knowledge_ids: [] },
    aidp: { mode: "inherit", kds_ids: [] },
  };
