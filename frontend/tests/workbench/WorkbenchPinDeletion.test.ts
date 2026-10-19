// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { QueryClient } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";
import { createConversationThreadListAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";
import { conversationService } from "@/services/conversationService";
import {
  removeDeletedWorkbenchPins,
  workbenchPinsQueryKey,
} from "@/lib/workbenchPins";

const history = (id: number) => ({
  conversation_id: id,
  conversation_title: `History ${id}`,
  create_time: 1,
  update_time: 1,
  pinned_at: "2026-10-19T00:00:00Z",
});

it("does not rehydrate a deleted pin when history reload uses the shared cache", async () => {
  const client = new QueryClient();
  const queryKey = workbenchPinsQueryKey("owner");
  client.setQueryData(queryKey, { items: [history(42), history(43)] });
  vi.spyOn(conversationService, "getList").mockResolvedValue({
    items: [],
    metadata: { total: 0, today: 0, last_7_days: 0, older: 0 },
  });
  const adapter = createConversationThreadListAdapter(
    "workbench",
    "owner",
    () =>
      client.ensureQueryData({
        queryKey,
        queryFn: () => conversationService.getWorkbenchPins(),
      })
  );
  await removeDeletedWorkbenchPins(client, [42]);
  expect((await adapter.list({})).threads.map((item) => item.remoteId)).toEqual(
    ["43"]
  );
  client.clear();
});

it("preserves failed deletions and unrelated pins across cached scopes", async () => {
  const client = new QueryClient();
  const key = workbenchPinsQueryKey("owner");
  const otherKey = workbenchPinsQueryKey("other-scope");
  client.setQueryData(key, { items: [history(42), history(43), history(44)] });
  client.setQueryData(otherKey, { items: [history(45)] });
  await removeDeletedWorkbenchPins(client, [42, 43], [43]);
  expect(client.getQueryData(key)).toEqual({
    items: [history(43), history(44)],
  });
  expect(client.getQueryData(otherKey)).toEqual({ items: [history(45)] });
  await removeDeletedWorkbenchPins(client, [43], [43]);
  expect(client.getQueryData(key)).toEqual({
    items: [history(43), history(44)],
  });
  client.clear();
});

it("cancels an in-flight pin refresh before pruning and leaves absent caches absent", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const key = workbenchPinsQueryKey("owner");
  client.setQueryData(key, { items: [history(42)] });
  let finish!: (value: { items: ReturnType<typeof history>[] }) => void;
  const refresh = client
    .fetchQuery({
      queryKey: key,
      queryFn: () =>
        new Promise<{ items: ReturnType<typeof history>[] }>((resolve) => {
          finish = resolve;
        }),
    })
    .catch(() => undefined);
  await removeDeletedWorkbenchPins(client, [42]);
  finish({ items: [history(42)] });
  await refresh;
  expect(client.getQueryData(key)).toEqual({ items: [] });
  expect(client.getQueryData(workbenchPinsQueryKey("absent"))).toBeUndefined();
  client.clear();
});
