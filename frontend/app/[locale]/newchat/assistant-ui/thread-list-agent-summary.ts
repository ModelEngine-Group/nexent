// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ConversationAgentSummaryItem } from "@/types/conversation";

type SummarizedAgentGroup = {
  agentId: number | null;
  conversationCount?: number;
};

/**
 * Merge per-agent summary rows into the groups derived from loaded
 * conversations. The merge attaches each row's conversation count (mutating
 * the freshly built group objects), creates a placeholder group for agents
 * whose conversations have not paginated into the loaded window yet, and
 * orders every group by its latest activity — the summary timestamp or the
 * group's newest loaded entry, whichever is later. The null-agent group
 * stays last.
 *
 * Returns the loaded groups unchanged while the summary is still loading
 * (undefined), so the sidebar keeps its current behavior until data arrives.
 */
export function mergeAgentSummaryGroups<T extends SummarizedAgentGroup>(
  loadedGroups: readonly T[],
  summary: readonly ConversationAgentSummaryItem[] | undefined,
  newestLoadedActivity: (group: T) => number | undefined,
  createPlaceholder: (row: ConversationAgentSummaryItem) => T
): T[] {
  if (!summary) return [...loadedGroups];

  const byAgent = new Map<number | null, T>();
  for (const group of loadedGroups) byAgent.set(group.agentId, group);

  const summaryActivity = new Map<number | null, number>();
  const merged: T[] = [];
  const summarized = new Set<number | null>();
  for (const row of summary) {
    summarized.add(row.agent_id);
    if (row.last_activity_time != null) {
      summaryActivity.set(row.agent_id, row.last_activity_time);
    }
    const existing = byAgent.get(row.agent_id);
    if (existing) {
      existing.conversationCount = row.conversation_count;
      merged.push(existing);
    } else {
      const placeholder = createPlaceholder(row);
      placeholder.conversationCount = row.conversation_count;
      merged.push(placeholder);
    }
  }
  // Loaded-only groups (e.g. brand-new local drafts) are not covered by the
  // summary; keep them and order everything by activity below.
  for (const group of loadedGroups) {
    if (!summarized.has(group.agentId)) merged.push(group);
  }

  const activityOf = (group: T): number => {
    const summaryTime = summaryActivity.get(group.agentId);
    const loadedTime = newestLoadedActivity(group);
    return Math.max(summaryTime ?? 0, loadedTime ?? 0);
  };
  const nonNull = merged.filter((group) => group.agentId !== null);
  const nullGroups = merged.filter((group) => group.agentId === null);
  nonNull.sort((left, right) => activityOf(right) - activityOf(left));
  return [...nonNull, ...nullGroups];
}
