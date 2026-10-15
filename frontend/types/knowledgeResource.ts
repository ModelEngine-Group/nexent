// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/**
 * Shared types for the knowledge resource status API used by the per-item
 * warning markers in the agent configuration and conversation selectors, and
 * for the deletion reference preview used by the delete confirmation dialog.
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

export interface KnowledgeReferencePreviewAgent {
  agent_id: number;
  display_name: string;
}

export interface KnowledgeReferencePreview {
  /** One entry per agent; draft and published versions collapse into it. */
  agents: KnowledgeReferencePreviewAgent[];
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
