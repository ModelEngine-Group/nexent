// Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import type { ConversationListPage } from "@/types/conversation";

export interface AgentConversationSelectionSummary {
  selectedCount: number;
  totalCount: number;
  checked: boolean;
  indeterminate: boolean;
}

export const getAgentConversationSelectionSummary = (
  selectedIds: ReadonlySet<string>,
  conversationIds: readonly string[]
): AgentConversationSelectionSummary => {
  const uniqueIds = [...new Set(conversationIds)];
  const selectedCount = uniqueIds.filter((id) => selectedIds.has(id)).length;
  return {
    selectedCount,
    totalCount: uniqueIds.length,
    checked: uniqueIds.length > 0 && selectedCount === uniqueIds.length,
    indeterminate: selectedCount > 0 && selectedCount < uniqueIds.length,
  };
};

export const setAgentConversationSelection = (
  selectedIds: ReadonlySet<string>,
  conversationIds: readonly string[],
  selected: boolean
): Set<string> => {
  const next = new Set(selectedIds);
  for (const id of conversationIds) {
    if (selected) next.add(id);
    else next.delete(id);
  }
  return next;
};

export const toggleAgentConversationSelection = (
  selectedIds: ReadonlySet<string>,
  conversationIds: readonly string[]
): Set<string> => {
  const uniqueIds = [...new Set(conversationIds)];
  const shouldDeselect =
    uniqueIds.length > 0 && uniqueIds.every((id) => selectedIds.has(id));
  return setAgentConversationSelection(selectedIds, uniqueIds, !shouldDeselect);
};

export const fetchAgentConversationIds = async (
  agentId: number,
  fetchPage: (offset: number, limit: number) => Promise<ConversationListPage>,
  pageSize = 100
): Promise<string[]> => {
  const conversationIds = new Set<string>();
  let offset = 0;
  let total: number | undefined;

  while (total === undefined || offset < total) {
    const page = await fetchPage(offset, pageSize);
    const pageTotal = Number(page.metadata?.total);
    if (Number.isFinite(pageTotal) && pageTotal >= 0) total = pageTotal;

    for (const conversation of page.items) {
      const conversationId = Number(conversation.conversation_id);
      if (
        conversation.agent_id === agentId &&
        Number.isSafeInteger(conversationId) &&
        conversationId > 0
      ) {
        conversationIds.add(String(conversationId));
      }
    }

    if (page.items.length < pageSize) break;
    const nextOffset = offset + page.items.length;
    if (nextOffset <= offset) break;
    offset = nextOffset;
  }

  return [...conversationIds];
};
