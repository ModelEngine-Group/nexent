// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/**
 * Shared types for the knowledge resource status API used by the per-item
 * warning markers in the agent configuration and conversation selectors.
 */

export type KnowledgeResourceProvider = "local" | "aidp";

export type KnowledgeResourceStatus =
  "available" | "not_found" | "inaccessible" | "lookup_failed";

export interface KnowledgeResourceStatusEntry {
  provider: KnowledgeResourceProvider;
  resource_id: string;
  status: KnowledgeResourceStatus;
  reason_code?: string | null;
  retryable?: boolean;
}

export type KnowledgeResourceContext =
  | { type: "agent"; agent_id: number }
  | { type: "conversation"; conversation_id: number }
  | { type: "selection" };

export interface KnowledgeReferenceVersion {
  version_no: number;
  version_name?: string | null;
  is_draft: boolean;
  reference_origin: "tool" | "skill";
}

export interface KnowledgeReferenceVisibleAgent {
  agent_id: number;
  display_name: string;
  can_edit_draft: boolean;
  versions: KnowledgeReferenceVersion[];
}

export interface KnowledgeReferenceConflictDetails {
  reason: "agent_references";
  visible_agents: KnowledgeReferenceVisibleAgent[];
  hidden_agent_count: number;
  total_agent_count: number;
}

export const knowledgeResourceKey = (
  provider: KnowledgeResourceProvider,
  resourceId: string
): string => `${provider}:${String(resourceId)}`;

/** Return whether one status entry should render as an anomaly marker. */
export const isWarningStatus = (status?: KnowledgeResourceStatus): boolean =>
  status !== undefined && status !== "available";
