// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it, vi } from "vitest";
import {
  createConversationThreadListAdapter,
  requestAgentConversationLoad,
} from "@/app/newchat/adapter/conversation-thread-list-adapter";
import { conversationService } from "@/services/conversationService";

const row = (id: number, activity = id) => ({
  conversation_id: id,
  conversation_title: `History ${id}`,
  create_time: 1,
  update_time: 9999,
  last_activity_time: activity,
});
const agentRow = (id: number, agentId: number, activity = id) => ({
  ...row(id, activity),
  agent_id: agentId,
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

it("uses keyset cursors and reloads the entire loaded window, preserving cursor semantics", async () => {
  const get = vi
    .spyOn(conversationService, "getList")
    .mockResolvedValueOnce({
      items: Array.from({ length: 30 }, (_, i) => row(140 - i)),
      metadata,
      next_cursor: "first",
    })
    .mockResolvedValueOnce({
      items: Array.from({ length: 20 }, (_, i) => row(110 - i)),
      metadata,
      next_cursor: "tail",
    })
    .mockResolvedValueOnce({
      items: [
        row(1, 200),
        ...Array.from({ length: 49 }, (_, i) => row(140 - i)),
      ],
      metadata,
      next_cursor: "rebased",
    });
  const adapter = createConversationThreadListAdapter("agent_chat");
  const initial = await adapter.list({});
  expect(initial.nextCursor).toBe("activity:first");
  const more = await adapter.list({ after: initial.nextCursor });
  expect(get.mock.calls[1][0]).toMatchObject({ offset: 0, cursor: "first" });
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

it("serves a requested agent page without advancing the global cursor", async () => {
  const get = vi
    .spyOn(conversationService, "getList")
    .mockResolvedValueOnce({
      items: Array.from({ length: 30 }, (_, i) => row(140 - i)),
      metadata,
      next_cursor: "first",
    })
    .mockResolvedValueOnce({
      items: [agentRow(7, 9, 70), agentRow(3, 9, 30)],
      metadata,
      next_cursor: null,
    })
    .mockResolvedValueOnce({
      items: [row(20)],
      metadata,
      next_cursor: "second",
    });
  const adapter = createConversationThreadListAdapter("agent_chat");
  const initial = await adapter.list({});
  expect(initial.nextCursor).toBe("activity:first");

  requestAgentConversationLoad("agent_chat", 9);
  const injected = await adapter.list({ after: initial.nextCursor });
  expect(get.mock.calls[1][0]).toMatchObject({
    offset: 0,
    limit: 100,
    agentId: 9,
    conversationType: "agent_chat",
  });
  expect(injected.threads).toHaveLength(2);
  expect(injected.threads[0].custom?.agentId).toBe(9);
  // The global cursor survives the injection so ordinary load-more
  // continues the activity stream exactly where it was.
  expect(injected.nextCursor).toBe("activity:first");

  const more = await adapter.list({ after: initial.nextCursor });
  expect(get.mock.calls[2][0]).not.toHaveProperty("agentId");
  expect(more.nextCursor).toBe("activity:second");
});

it("re-queues a failed agent page so a later load-more retries it", async () => {
  vi.spyOn(conversationService, "getList")
    .mockResolvedValueOnce({
      items: [row(1)],
      metadata,
      next_cursor: "k1",
    })
    .mockRejectedValueOnce(new Error("network down"))
    .mockResolvedValueOnce({
      items: [agentRow(9, 4, 90)],
      metadata,
      next_cursor: null,
    });
  const adapter = createConversationThreadListAdapter("agent_chat");
  const initial = await adapter.list({});
  requestAgentConversationLoad("agent_chat", 4);
  await expect(adapter.list({ after: initial.nextCursor })).rejects.toThrow(
    "network down"
  );
  const retried = await adapter.list({ after: initial.nextCursor });
  expect(retried.threads[0].custom?.agentId).toBe(4);
  expect(retried.nextCursor).toBe(initial.nextCursor);
});

it("collapses duplicate agent requests into a single injection", async () => {
  const get = vi
    .spyOn(conversationService, "getList")
    .mockResolvedValueOnce({
      items: Array.from({ length: 30 }, (_, i) => row(140 - i)),
      metadata,
      next_cursor: "first",
    })
    .mockResolvedValueOnce({
      items: [agentRow(9, 5, 90)],
      metadata,
      next_cursor: null,
    })
    .mockResolvedValueOnce({
      items: [row(20)],
      metadata,
      next_cursor: "second",
    });
  const adapter = createConversationThreadListAdapter("agent_chat");
  const initial = await adapter.list({});
  requestAgentConversationLoad("agent_chat", 5);
  requestAgentConversationLoad("agent_chat", 5);
  const injected = await adapter.list({ after: initial.nextCursor });
  expect(injected.threads[0].custom?.agentId).toBe(5);
  // The duplicate request was collapsed: the next load-more advances the
  // global stream instead of re-serving the agent page.
  await adapter.list({ after: initial.nextCursor });
  expect(get.mock.calls[2][0]).not.toHaveProperty("agentId");
});

it("clears pending agent requests when the list reloads from scratch", async () => {
  const get = vi.spyOn(conversationService, "getList").mockResolvedValue({
    items: [row(1)],
    metadata,
    next_cursor: "k1",
  });
  const adapter = createConversationThreadListAdapter("agent_chat");
  const initial = await adapter.list({});
  expect(initial.nextCursor).toBe("activity:k1");
  requestAgentConversationLoad("agent_chat", 5);
  const refreshed = await adapter.list({});
  expect(get.mock.calls[1][0]).not.toHaveProperty("agentId");
  expect(refreshed.threads.map((item) => item.remoteId)).toEqual(["1"]);
  const more = await adapter.list({ after: initial.nextCursor });
  expect(get.mock.calls[2][0]).not.toHaveProperty("agentId");
  expect(more.threads.map((item) => item.remoteId)).toEqual(["1"]);
});
