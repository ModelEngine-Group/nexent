// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, render, waitFor } from "@testing-library/react";
import {
  focusManager,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { expect, it, vi } from "vitest";
import { PinnedThreadsProvider } from "@/app/newchat/assistant-ui/thread-pins";
import { WorkbenchPinHistorySync } from "@/app/newchat/assistant-ui/workbench-pin-history-sync";
import { createConversationThreadListAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";
import { conversationService } from "@/services/conversationService";
import { workbenchPinsQueryKey } from "@/lib/workbenchPins";

const runtime = vi.hoisted(() => ({
  state: {
    threads: {
      threadIds: [] as string[],
      threadItems: [] as Array<{ id: string; remoteId: string }>,
      isLoading: false,
      isLoadingMore: false,
    },
  },
  reload: vi.fn<() => Promise<void>>(),
}));
vi.mock("@assistant-ui/react", async (original) => ({
  ...(await original<typeof import("@assistant-ui/react")>()),
  useAui: () => ({ threads: () => ({ reload: runtime.reload }) }),
  useAuiState: (select: (state: typeof runtime.state) => unknown) =>
    select(runtime.state),
}));
const history = (id: number) => ({
  conversation_id: id,
  conversation_title: `History ${id}`,
  create_time: 1,
  update_time: 1,
  pinned_at: "2026-10-16T00:00:00Z",
});
function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = () => (
    <QueryClientProvider client={client}>
      <PinnedThreadsProvider serverBacked storageKey="sync-user">
        <WorkbenchPinHistorySync />
      </PinnedThreadsProvider>
    </QueryClientProvider>
  );
  const result = render(view());
  return { ...result, client, view };
}

it("refocus hydrates an unloaded remote pin using the confirmed snapshot, without duplicate requests", async () => {
  runtime.state.threads = {
    threadIds: ["local"],
    threadItems: [{ id: "local", remoteId: "42" }],
    isLoading: false,
    isLoadingMore: false,
  };
  const get = vi
    .spyOn(conversationService, "getWorkbenchPins")
    .mockResolvedValueOnce({ items: [history(42)] })
    .mockResolvedValue({ items: [history(900), history(42)] });
  vi.spyOn(conversationService, "getList").mockResolvedValue({
    items: [history(42)],
    metadata: { total: 31, today: 1, last_7_days: 0, older: 30 },
  });
  const { client } = setup();
  const adapter = createConversationThreadListAdapter(
    "workbench",
    "sync-user",
    () =>
      client.ensureQueryData({
        queryKey: workbenchPinsQueryKey("sync-user"),
        queryFn: () => conversationService.getWorkbenchPins(),
      })
  );
  runtime.reload.mockImplementation(async () => {
    const result = await adapter.list({});
    expect(result.threads.map((item) => item.remoteId)).toEqual(["42", "900"]);
    expect(result.nextCursor).toBe("1");
    runtime.state.threads.threadIds = ["local", "older"];
    runtime.state.threads.threadItems = [
      { id: "local", remoteId: "42" },
      { id: "older", remoteId: "900" },
    ];
  });
  await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
  expect(runtime.reload).not.toHaveBeenCalled();
  act(() => {
    focusManager.setFocused(false);
    focusManager.setFocused(true);
  });
  await waitFor(() => expect(runtime.reload).toHaveBeenCalledTimes(1));
  await waitFor(() =>
    expect(
      runtime.state.threads.threadItems.find((item) => item.id === "older")
        ?.remoteId
    ).toBe("900")
  );
  expect(get).toHaveBeenCalledTimes(2);
  focusManager.setFocused(undefined);
  client.clear();
});

it("waits for paging to settle and attempts each successful refresh at most once", async () => {
  runtime.reload.mockReset().mockResolvedValue();
  runtime.state.threads = {
    threadIds: [],
    threadItems: [],
    isLoading: false,
    isLoadingMore: true,
  };
  const get = vi
    .spyOn(conversationService, "getWorkbenchPins")
    .mockResolvedValue({ items: [history(900)] });
  const { client, rerender, view } = setup();
  await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
  expect(runtime.reload).not.toHaveBeenCalled();
  runtime.state.threads.isLoadingMore = false;
  rerender(view());
  await waitFor(() => expect(runtime.reload).toHaveBeenCalledTimes(1));
  rerender(view());
  expect(runtime.reload).toHaveBeenCalledTimes(1);
  client.clear();
});

it("a failed pin refresh does not reload or discard the confirmed history", async () => {
  runtime.reload.mockReset().mockResolvedValue();
  runtime.state.threads = {
    threadIds: ["local"],
    threadItems: [{ id: "local", remoteId: "42" }],
    isLoading: false,
    isLoadingMore: false,
  };
  vi.spyOn(conversationService, "getWorkbenchPins").mockRejectedValue(
    new Error("unavailable")
  );
  const { client } = setup();
  await waitFor(() =>
    expect(
      client.getQueryState(workbenchPinsQueryKey("sync-user"))?.status
    ).toBe("error")
  );
  expect(runtime.reload).not.toHaveBeenCalled();
  expect(runtime.state.threads.threadItems[0].remoteId).toBe("42");
  client.clear();
});

it("cached metadata outside the listed IDs still requires hydration", async () => {
  runtime.reload.mockReset().mockResolvedValue();
  runtime.state.threads = {
    threadIds: ["local"],
    threadItems: [
      { id: "local", remoteId: "42" },
      { id: "cached", remoteId: "900" },
    ],
    isLoading: false,
    isLoadingMore: false,
  };
  vi.spyOn(conversationService, "getWorkbenchPins").mockResolvedValue({
    items: [history(900)],
  });
  const { client } = setup();
  await waitFor(() => expect(runtime.reload).toHaveBeenCalledTimes(1));
  client.clear();
});
