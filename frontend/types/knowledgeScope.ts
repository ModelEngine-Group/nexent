// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

export type KnowledgeScopeMode = "inherit" | "override" | "disabled";
export type AidpMetadataFilterOperator =
  "contains" | "is" | "starts_with" | "ends_with";

export interface AidpFileNameCondition {
  operator: AidpMetadataFilterOperator;
  value: string;
}

export interface AidpMetadataFilter {
  enabled: boolean;
  file_name?: AidpFileNameCondition;
}

export interface ConversationKnowledgeScope {
  schema_version: 1 | 2 | 3;
  local: {
    mode: KnowledgeScopeMode;
    knowledge_ids: string[];
  };
  aidp: {
    mode: KnowledgeScopeMode;
    kds_ids: string[];
    metadata_filter?: AidpMetadataFilter;
  };
}

export const EMPTY_AIDP_METADATA_FILTER: AidpMetadataFilter = {
  enabled: false,
};

export function getAidpMetadataFilter(
  scope: ConversationKnowledgeScope | null | undefined
): AidpMetadataFilter {
  const filter = scope?.aidp.metadata_filter;
  if (!filter?.enabled || !filter.file_name?.value) {
    return EMPTY_AIDP_METADATA_FILTER;
  }
  return {
    enabled: true,
    file_name: {
      operator: filter.file_name.operator,
      value: filter.file_name.value,
    },
  };
}

export function withAidpMetadataFilter(
  scope: ConversationKnowledgeScope | null | undefined,
  filter: AidpMetadataFilter | null | undefined
): ConversationKnowledgeScope {
  const base = scope ?? DEFAULT_CONVERSATION_KNOWLEDGE_SCOPE;
  const enabled = Boolean(
    filter?.enabled && filter.file_name?.value && base.aidp.mode !== "disabled"
  );
  const normalized: AidpMetadataFilter | undefined = enabled
    ? {
        enabled: true,
        file_name: {
          operator: filter!.file_name!.operator,
          value: filter!.file_name!.value,
        },
      }
    : undefined;
  return {
    ...base,
    schema_version: normalized ? 3 : (base.schema_version ?? 1),
    local: { ...base.local },
    aidp: {
      mode: base.aidp.mode,
      kds_ids: [...base.aidp.kds_ids],
      ...(normalized ? { metadata_filter: normalized } : {}),
    },
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
      default_knowledge_ids: string[];
      default_range_values: string[];
    };
    aidp: {
      enabled: boolean;
      max_select: number;
      metadata_filter_supported?: boolean;
      metadata_filter_graph_supported?: boolean;
      default_summary: string;
      default_knowledge_ids: string[];
      default_range_values: string[];
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
    metadata_filter?: AidpMetadataFilter;
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
