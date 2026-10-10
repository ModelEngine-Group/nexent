import { useQuery } from "@tanstack/react-query";
import { conversationService } from "@/services/conversationService";
import { getConversationDateBoundaries } from "@/lib/conversationViewport";
import type { ConversationListItem } from "@/types/conversation";

/**
 * Loads the user's recent conversations (most recent first) so the agent
 * landing can derive which agents have had conversations.
 */
export function useConversationAgentHistory(limit = 50) {
  return useQuery<ConversationListItem[]>({
    queryKey: ["conversationAgentHistory", limit],
    queryFn: async () => {
      const { todayStartMs, weekStartMs } = getConversationDateBoundaries();
      const page = await conversationService.getList({
        offset: 0,
        limit,
        todayStartMs,
        weekStartMs,
      });
      return page.items;
    },
    staleTime: 30_000,
  });
}
