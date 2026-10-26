// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { describe, expect, test } from "vitest";

import { mergeAgentSummaryGroups } from "@/app/newchat/assistant-ui/thread-list-agent-summary";
import type { ConversationAgentSummaryItem } from "@/types/conversation";

type Group = {
  agentId: number | null;
  entries: string[];
  conversationCount?: number;
};

const group = (agentId: number | null, entries: string[] = []): Group => ({
  agentId,
  entries,
});

const summaryRow = (
  agentId: number | null,
  conversationCount: number,
  lastActivityTime: number | null
): ConversationAgentSummaryItem => ({
  agent_id: agentId,
  conversation_count: conversationCount,
  last_activity_time: lastActivityTime,
});

const merge = (
  groups: Group[],
  summary: ConversationAgentSummaryItem[] | undefined,
  activities: Partial<Record<number | "null", number>> = {}
) =>
  mergeAgentSummaryGroups(
    groups,
    summary,
    (item) => activities[item.agentId ?? "null"],
    (row) => group(row.agent_id)
  );

describe("mergeAgentSummaryGroups", () => {
  test("keeps loaded groups unchanged while the summary is loading", () => {
    const groups = [group(1, ["a"]), group(null, ["b"])];
    const merged = merge(groups, undefined);
    expect(merged).toEqual(groups);
  });

  test("creates placeholder groups for agents without loaded conversations", () => {
    const merged = merge(
      [group(1, ["a"])],
      [summaryRow(1, 5, 100), summaryRow(2, 3, 50)]
    );
    expect(merged.map((item) => item.agentId)).toEqual([1, 2]);
    expect(merged[0].conversationCount).toBe(5);
    expect(merged[1].entries).toEqual([]);
    expect(merged[1].conversationCount).toBe(3);
  });

  test("keeps groups that exist only among loaded conversations", () => {
    const merged = merge(
      [group(1, ["a"]), group(2, ["b"])],
      [summaryRow(1, 1, 100)]
    );
    expect(merged.map((item) => item.agentId)).toEqual([1, 2]);
    expect(merged[1].conversationCount).toBeUndefined();
  });

  test("orders groups by the later of summary activity and newest entry", () => {
    const merged = merge(
      [group(1, ["a"]), group(2, ["b"])],
      [summaryRow(1, 1, 100), summaryRow(2, 2, 50)],
      { 2: 200 }
    );
    // Agent 2's newest loaded entry (200) beats agent 1's summary activity.
    expect(merged.map((item) => item.agentId)).toEqual([2, 1]);
  });

  test("keeps the null-agent group last regardless of activity", () => {
    const merged = merge(
      [group(null, ["a"])],
      [summaryRow(null, 1, 999), summaryRow(2, 2, 50)]
    );
    expect(merged.map((item) => item.agentId)).toEqual([2, null]);
    expect(merged[1].conversationCount).toBe(1);
  });

  test("sorts summary-only groups by their summary activity", () => {
    const merged = mergeAgentSummaryGroups(
      [],
      [summaryRow(3, 1, 10), summaryRow(1, 2, 300), summaryRow(2, 7, 100)],
      () => undefined,
      (row) => group(row.agent_id)
    );
    expect(merged.map((item) => item.agentId)).toEqual([1, 2, 3]);
    expect(merged.map((item) => item.conversationCount)).toEqual([2, 7, 1]);
  });
});
