import { expect, it, vi } from "vitest";
import { createConversationThreadListAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";
import { conversationService } from "@/services/conversationService";

const pinKey = "workbench-test-pins";
const listed = {
  conversation_id: 1,
  conversation_title: "Recent",
  create_time: Date.now(),
  update_time: Date.now(),
};
const metadata = { total: 31, today: 1, last_7_days: 0, older: 30 };

it("hydrates a pinned Workbench history beyond the initial page without advancing its cursor", async () => {
  localStorage.setItem(pinKey, '["42"]');
  const list = vi
    .spyOn(conversationService, "getList")
    .mockResolvedValueOnce({ items: [listed], metadata })
    .mockResolvedValueOnce({
      items: [
        { ...listed, conversation_id: 42 },
        { ...listed, conversation_id: 2 },
      ],
      metadata,
    });
  const pins = vi
    .spyOn(conversationService, "getWorkbenchPins")
    .mockResolvedValue({
      items: [
        {
          ...listed,
          conversation_id: 42,
          conversation_title: "Pinned older",
          pinned_at: new Date().toISOString(),
        },
      ],
    });
  const adapter = createConversationThreadListAdapter("workbench", pinKey);
  const first = await adapter.list({});
  expect(first.threads.map((item) => item.remoteId)).toEqual(["1", "42"]);
  expect(first.nextCursor).toBe("1");
  expect(pins).toHaveBeenCalledTimes(1);
  const next = await adapter.list({ after: first.nextCursor });
  expect(next.threads.map((item) => item.remoteId)).toEqual(["2"]);
  expect(next.nextCursor).toBe("3");
  expect(list.mock.lastCall?.[0]).toMatchObject({
    offset: 1,
    limit: 20,
    conversationType: "workbench",
  });
  expect(pins).toHaveBeenCalledTimes(1);
});

it("does not refetch a pin already present in the initial page", async () => {
  localStorage.setItem(pinKey, '["1"]');
  vi.spyOn(conversationService, "getList").mockResolvedValue({
    items: [listed],
    metadata,
  });
  vi.spyOn(conversationService, "getWorkbenchPins").mockResolvedValue({
    items: [{ ...listed, pinned_at: new Date().toISOString() }],
  });
  const detail = vi.spyOn(conversationService, "getById");
  expect(
    (await createConversationThreadListAdapter("workbench", pinKey).list({}))
      .threads
  ).toHaveLength(1);
  expect(detail).not.toHaveBeenCalled();
});

it("missing or foreign pins cannot fail ordinary history or hide later rows", async () => {
  localStorage.setItem(pinKey, '["42","43"]');
  vi.spyOn(conversationService, "getList").mockResolvedValue({
    items: [listed],
    metadata,
  });
  vi.spyOn(conversationService, "getWorkbenchPins").mockRejectedValue(
    new Error("Not accessible")
  );
  const response = await createConversationThreadListAdapter(
    "workbench",
    pinKey
  ).list({});
  expect(response.threads.map((item) => item.remoteId)).toEqual(["1"]);
  expect(response.nextCursor).toBe("1");
  expect(localStorage.getItem(pinKey)).toBe('["42","43"]');
});

it("Agent chat retains its original list behavior even when a pin scope is supplied", async () => {
  localStorage.setItem(pinKey, '["42"]');
  vi.spyOn(conversationService, "getList").mockResolvedValue({
    items: [listed],
    metadata,
  });
  const pins = vi.spyOn(conversationService, "getWorkbenchPins");
  const detail = vi.spyOn(conversationService, "getById");
  const response = await createConversationThreadListAdapter(
    "agent_chat",
    pinKey
  ).list({});
  expect(response.threads.map((item) => item.remoteId)).toEqual(["1"]);
  expect(detail).not.toHaveBeenCalled();
  expect(pins).not.toHaveBeenCalled();
});

it("unsent Workbench drafts have distinct local identities without backend creation", async () => {
  const requests = vi.spyOn(globalThis, "fetch");
  const adapter = createConversationThreadListAdapter("workbench");
  const a = await adapter.initialize("draft-a"),
    b = await adapter.initialize("draft-b");
  expect(a.remoteId).toBe("workbench-draft:draft-a");
  expect(b.remoteId).toBe("workbench-draft:draft-b");
  expect(a.remoteId).not.toBe(b.remoteId);
  expect(requests).not.toHaveBeenCalled();
});

it("ordinary Agent conversation initialization retains its existing contract", async () => {
  expect(
    await createConversationThreadListAdapter("agent_chat").initialize("draft")
  ).toEqual({ remoteId: "", externalId: "" });
});
