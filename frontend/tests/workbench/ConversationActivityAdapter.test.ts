// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it, vi } from "vitest";
import { createConversationThreadListAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";
import { conversationService } from "@/services/conversationService";

const row = (id: number, activity = id) => ({
  conversation_id: id,
  conversation_title: `History ${id}`,
  create_time: 1,
  update_time: 9999,
  last_activity_time: activity,
});
const metadata = { total: 140, today: 140, last_7_days: 0, older: 0 };

it("uses message activity instead of an administrative audit timestamp", async () => {
  vi.spyOn(conversationService, "getList").mockResolvedValue({
    items: [row(1, 100)],
    metadata,
    next_cursor: null,
  });
  const result = await createConversationThreadListAdapter("workbench").list(
    {}
  );
  expect(result.threads[0].custom?.lastMessageAt).toBe(
    new Date(100).toISOString()
  );
  expect(result.nextCursor).toBeUndefined();
});

it("leaves Agent-chat history loading to the grouped history API", async () => {
  const get = vi.spyOn(conversationService, "getList");
  const result = await createConversationThreadListAdapter("agent_chat").list(
    {}
  );

  expect(result).toEqual({ threads: [] });
  expect(get).not.toHaveBeenCalled();
});

it.each(["agent_chat", "workbench"] as const)(
  "limits detail activity metadata changes to Agent chat (%s)",
  async (conversationType) => {
    vi.spyOn(conversationService, "getById").mockResolvedValue({
      conversation_id: 7,
      create_time: 1000,
      last_activity_time: 9000,
      message: [],
    });
    const adapter = createConversationThreadListAdapter(conversationType);
    const result = await adapter.fetch("7");
    expect(result.custom?.lastMessageAt).toBe(
      new Date(conversationType === "agent_chat" ? 9000 : 1000).toISOString()
    );
  }
);

it("preserves Workbench keyset pagination and its loaded refresh window", async () => {
  const get = vi
    .spyOn(conversationService, "getList")
    .mockResolvedValueOnce({
      items: Array.from({ length: 30 }, (_, index) => row(140 - index)),
      metadata,
      next_cursor: "first",
    })
    .mockResolvedValueOnce({
      items: Array.from({ length: 20 }, (_, index) => row(110 - index)),
      metadata,
      next_cursor: "tail",
    })
    .mockResolvedValueOnce({
      items: [
        row(1, 200),
        ...Array.from({ length: 49 }, (_, index) => row(140 - index)),
      ],
      metadata,
      next_cursor: "rebased",
    });
  const adapter = createConversationThreadListAdapter("workbench");
  const initial = await adapter.list({});
  expect(initial.nextCursor).toBe("activity:first");
  const more = await adapter.list({ after: initial.nextCursor });
  expect(get.mock.calls[1][0]).toMatchObject({
    offset: 0,
    cursor: "first",
    conversationType: "workbench",
  });
  expect(more.nextCursor).toBe("activity:tail");
  const refreshed = await adapter.list({});
  expect(get.mock.calls[2][0]).toMatchObject({ offset: 0, limit: 50 });
  expect(refreshed.threads).toHaveLength(50);
  expect(refreshed.threads[0].remoteId).toBe("1");
  expect(refreshed.nextCursor).toBe("activity:rebased");
});

it("deduplicates remote identities when the live list changes during pagination", async () => {
  vi.spyOn(conversationService, "getList").mockResolvedValue({
    items: [row(1), row(1), row(2)],
    metadata,
    next_cursor: null,
  });
  const result = await createConversationThreadListAdapter("workbench").list(
    {}
  );
  expect(result.threads.map((item) => item.remoteId)).toEqual(["1", "2"]);
});

it("does not let a superseded page response overwrite the refreshed pagination window", async () => {
  let resolveOld!: (value: {
    items: ReturnType<typeof row>[];
    metadata: typeof metadata;
  }) => void;
  vi.spyOn(conversationService, "getList")
    .mockReturnValueOnce(
      new Promise((resolve) => {
        resolveOld = resolve;
      })
    )
    .mockResolvedValueOnce({ items: [row(7)], metadata, next_cursor: null });
  const adapter = createConversationThreadListAdapter("workbench");
  const old = adapter.list({});
  const fresh = await adapter.list({});
  resolveOld({ items: [row(1)], metadata });
  expect((await old).threads).toEqual([]);
  expect(fresh.threads.map((item) => item.remoteId)).toEqual(["7"]);
});
