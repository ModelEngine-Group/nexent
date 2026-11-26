// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { useQuery } from "@tanstack/react-query";
import { fetchNl2AgentKnowledgeRecommendations } from "@/services/nl2AgentKnowledgeService";
import type { Nl2aUnifiedResourcesPayload } from "../adapter/remote-chat-model-adapter";

export function useNl2AgentKnowledgeRecommendations(
  payload: Nl2aUnifiedResourcesPayload | undefined,
  enabled: boolean,
  scope: string
) {
  return useQuery({
    queryKey: [
      "nl2agent-knowledge-recommendations",
      scope,
      payload?.agent_id,
      payload?.conversation_id,
      payload?.card_id,
      payload?.state_version,
    ],
    enabled: Boolean(enabled && payload && Number(payload.conversation_id) > 0),
    queryFn: ({ signal }) =>
      fetchNl2AgentKnowledgeRecommendations(
        {
          agent_id: payload!.agent_id,
          conversation_id: Number(payload!.conversation_id),
          card_id: payload!.card_id,
          state_version: payload!.state_version,
        },
        signal
      ),
    retry: false,
    refetchOnWindowFocus: false,
    gcTime: 0,
  });
}
