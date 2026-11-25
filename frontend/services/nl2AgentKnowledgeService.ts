// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { fetchWithAuth } from "@/lib/auth";
import { API_ENDPOINTS } from "@/services/api";
import type {
  Nl2AgentKnowledgePreparation,
  Nl2AgentKnowledgeRequest,
} from "@/types/nl2AgentKnowledge";

export async function fetchNl2AgentKnowledgeRecommendations(
  request: Nl2AgentKnowledgeRequest,
  signal?: AbortSignal
): Promise<Nl2AgentKnowledgePreparation[]> {
  const response = await fetchWithAuth(
    API_ENDPOINTS.agent.nl2agentKnowledgeRecommendations,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal,
    }
  );
  if (!response.ok) throw new Error("Knowledge recommendations unavailable");
  const value = await response.json();
  if (
    !Array.isArray(value.resources) ||
    value.resources.some(
      (row: Nl2AgentKnowledgePreparation) =>
        typeof row.candidate_ref !== "string" ||
        !["knowledge_base_search", "aidp_search"].includes(row.tool_name) ||
        !Array.isArray(row.selected_values) ||
        row.selected_values.some((id) => typeof id !== "string") ||
        !["saved", "recommended"].includes(row.selection_source) ||
        !Array.isArray(row.recommendations) ||
        row.recommendations.length > 5 ||
        row.recommendations.some(
          (item) =>
            !item ||
            typeof item.id !== "string" ||
            typeof item.binding_value !== "string" ||
            typeof item.name !== "string" ||
            !Number.isFinite(item.score)
        ) ||
        !row.settings ||
        !row.models
    )
  )
    throw new Error("Invalid knowledge recommendations");
  return value.resources;
}
