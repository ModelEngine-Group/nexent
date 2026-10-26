// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useQuery } from "@tanstack/react-query";
import { conversationService } from "@/services/conversationService";

/**
 * Loads one summary row per agent that owns at least one conversation, so the
 * sidebar can render every agent group before its conversations paginate
 * into the activity-ordered list.
 */
export function useConversationAgentSummary(
  conversationType: "agent_chat" | "workbench",
  enabled = true
) {
  return useQuery({
    queryKey: ["conversationAgentSummary", conversationType],
    queryFn: () => conversationService.getAgentSummary(conversationType),
    enabled,
    staleTime: 30_000,
  });
}
