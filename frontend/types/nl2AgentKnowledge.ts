// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
export interface Nl2AgentKnowledgeModels {
  embedding_model_id?: number | null;
  embedding_model_name?: string | null;
  multi_embedding_model_id?: number | null;
  multi_embedding_model_name?: string | null;
}

export interface Nl2AgentKnowledgePreparation {
  candidate_ref: string;
  tool_name: "knowledge_base_search" | "aidp_search";
  recommendations: Array<{
    id: string;
    binding_value: string;
    name: string;
    score: number;
  }>;
  selected_values: string[];
  selection_source: "saved" | "recommended";
  settings: { top_k?: number; multimodal?: boolean };
  models: Nl2AgentKnowledgeModels;
  mode: "text" | "hybrid" | "fallback";
}

export interface Nl2AgentKnowledgeRequest {
  agent_id: number;
  conversation_id: number;
  card_id: string;
  state_version: number;
}
