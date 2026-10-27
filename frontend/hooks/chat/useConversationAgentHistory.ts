// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useQuery } from "@tanstack/react-query";
import { conversationService } from "@/services/conversationService";
import type { AgentConversationGroup } from "@/types/conversation";

/**
 * Loads all Agent history summaries so the landing can show every recently
 * used Agent without inferring groups from a truncated conversation page.
 */
export function useConversationAgentHistory(pageSize = 100) {
  return useQuery<AgentConversationGroup[]>({
    queryKey: ["conversationAgentHistory", pageSize],
    queryFn: async () => {
      const groups: AgentConversationGroup[] = [];
      let cursor: string | null | undefined;
      do {
        const page = await conversationService.getAgentGroups({
          limit: pageSize,
          cursor,
        });
        groups.push(...page.items);
        cursor = page.next_cursor;
      } while (cursor);
      return groups;
    },
    staleTime: 30_000,
  });
}
