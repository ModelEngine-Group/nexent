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
  capability_revision?: string;
  legacy_prompt_warning?: {
    detected: boolean;
    affected_agent_ids: number[];
    reason_code: "STATIC_KNOWLEDGE_SCOPE_REFERENCE";
  };
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

export interface KnowledgeScopeWarning {
  code: string;
  source?: "local" | "aidp";
  count: number;
}

export interface KnowledgeScopeEffectivePreview {
  local: {
    disabled: boolean;
    knowledge_ids: string[];
    display_names: string[];
  };
  aidp: {
    disabled: boolean;
    kds_ids: string[];
    display_names: string[];
  };
}

export interface KnowledgeScopeUpdateResult {
  desired_scope: ConversationKnowledgeScope | null;
  effective_preview: KnowledgeScopeEffectivePreview | null;
  warnings: KnowledgeScopeWarning[];
}

export interface KnowledgeScopeResolution {
  effective: KnowledgeScopeEffectivePreview;
  warnings: KnowledgeScopeWarning[];
}

export const DEFAULT_CONVERSATION_KNOWLEDGE_SCOPE: ConversationKnowledgeScope =
  {
    schema_version: 1,
    local: { mode: "inherit", knowledge_ids: [] },
    aidp: { mode: "inherit", kds_ids: [] },
  };
