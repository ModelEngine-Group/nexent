// Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import { describe, expect, test, vi } from "vitest";

import {
  fetchAgentConversationIds,
  getAgentConversationSelectionSummary,
  toggleAgentConversationSelection,
} from "@/lib/agentConversationSelection";
import type { ConversationListPage } from "@/types/conversation";

const page = (
  items: ConversationListPage["items"],
  total: number
): ConversationListPage => ({
  items,
  metadata: { total, today: 0, last_7_days: 0, older: total },
});

describe("agent conversation selection", () => {
  test("selects all matching conversations across pages and ignores other agents", async () => {
    const fetchPage = vi
      .fn<(offset: number, limit: number) => Promise<ConversationListPage>>()
      .mockResolvedValueOnce(
        page(
          [
            {
              conversation_id: 10,
              agent_id: 7,
              conversation_title: "a",
              create_time: 0,
              update_time: 0,
            },
            {
              conversation_id: 11,
              agent_id: 8,
              conversation_title: "b",
              create_time: 0,
              update_time: 0,
            },
          ],
          3
        )
      )
      .mockResolvedValueOnce(
        page(
          [
            {
              conversation_id: 12,
              agent_id: 7,
              conversation_title: "c",
              create_time: 0,
              update_time: 0,
            },
            {
              conversation_id: 10,
              agent_id: 7,
              conversation_title: "duplicate",
              create_time: 0,
              update_time: 0,
            },
          ],
          3
        )
      );

    await expect(fetchAgentConversationIds(7, fetchPage, 2)).resolves.toEqual([
      "10",
      "12",
    ]);
    expect(fetchPage.mock.calls).toEqual([
      [0, 2],
      [2, 2],
    ]);
  });

  test("propagates a failed page so callers cannot act on partial results", async () => {
    const fetchPage = vi
      .fn<(offset: number, limit: number) => Promise<ConversationListPage>>()
      .mockResolvedValueOnce(
        page(
          [
            {
              conversation_id: 10,
              agent_id: 7,
              conversation_title: "a",
              create_time: 0,
              update_time: 0,
            },
          ],
          2
        )
      )
      .mockRejectedValueOnce(new Error("page failed"));

    await expect(fetchAgentConversationIds(7, fetchPage, 1)).rejects.toThrow(
      "page failed"
    );
  });

  test("toggles a complete agent group while preserving other selections", () => {
    const selected = new Set(["11", "20"]);
    const selectedGroup = toggleAgentConversationSelection(selected, [
      "10",
      "11",
      "12",
    ]);
    expect(selectedGroup).toEqual(new Set(["10", "11", "12", "20"]));
    expect(
      getAgentConversationSelectionSummary(selectedGroup, ["10", "11", "12"])
    ).toEqual({
      selectedCount: 3,
      totalCount: 3,
      checked: true,
      indeterminate: false,
    });
    expect(
      toggleAgentConversationSelection(selectedGroup, ["10", "11", "12"])
    ).toEqual(new Set(["20"]));
  });
});
