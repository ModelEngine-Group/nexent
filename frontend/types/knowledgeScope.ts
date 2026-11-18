// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

export type KnowledgeScopeMode = "inherit" | "override" | "disabled";
export type AidpFileScopeMode = "all" | "selected";

export interface AidpFileRef {
  kds_id: string;
  file_uuid: string;
  file_name?: string;
  kds_name?: string;
}

export interface AidpFileScope {
  mode: AidpFileScopeMode;
  files: AidpFileRef[];
}

export interface ConversationKnowledgeScope {
  schema_version: 1 | 2;
  local: {
    mode: KnowledgeScopeMode;
    knowledge_ids: string[];
  };
  aidp: {
    mode: KnowledgeScopeMode;
    kds_ids: string[];
    file_scope?: AidpFileScope;
  };
}

export const EMPTY_AIDP_FILE_SCOPE: AidpFileScope = { mode: "all", files: [] };

export function getAidpFileScope(
  scope: ConversationKnowledgeScope | null | undefined
): AidpFileScope {
  const fileScope = scope?.aidp.file_scope;
  if (!fileScope || fileScope.mode !== "selected") {
    return EMPTY_AIDP_FILE_SCOPE;
  }
  return {
    mode: "selected",
    files: Array.isArray(fileScope.files) ? fileScope.files : [],
  };
}

export function withAidpFileScope(
  scope: ConversationKnowledgeScope | null | undefined,
  fileScope: AidpFileScope
): ConversationKnowledgeScope {
  const base = scope ?? DEFAULT_CONVERSATION_KNOWLEDGE_SCOPE;
  const normalized: AidpFileScope =
    fileScope.mode === "selected" && fileScope.files.length > 0
      ? {
          mode: "selected",
          files: fileScope.files.map((file) => ({ ...file })),
        }
      : EMPTY_AIDP_FILE_SCOPE;
  return {
    ...base,
    schema_version:
      normalized.mode === "selected" ? 2 : (base.schema_version ?? 1),
    local: { ...base.local },
    aidp: {
      ...base.aidp,
      ...(normalized.mode === "selected" || base.aidp.file_scope
        ? { file_scope: normalized }
        : {}),
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
      max_file_select?: number;
      file_scope_supported?: boolean;
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
    file_scope?: AidpFileScope;
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
