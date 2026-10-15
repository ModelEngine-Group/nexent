// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** Knowledge binding preview contracts for deletion confirmation. */

export type KnowledgeResourceProvider = "local" | "aidp";

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
