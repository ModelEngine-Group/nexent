// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import type { PropsWithChildren } from "react";
import { renderToString } from "react-dom/server";
import { useConversationActivitySync } from "@/hooks/chat/useConversationActivitySync";
import { conversationService } from "@/services/conversationService";

const state = vi.hoisted(() => ({
  items: [] as Array<{
    id: string;
    remoteId: string;
    title: string;
    custom: { lastMessageAt: string };
  }>,
  busy: false,
  reload: vi.fn<() => Promise<void>>(),
  runEnd: undefined as undefined | (() => void),
}));
vi.mock("@assistant-ui/react", () => ({
  useAui: () => client,
  useAuiEvent: (_event: unknown, callback: () => void) => {
    state.runEnd = callback;
  },
  useAuiState: (selector: (value: unknown) => unknown) =>
    selector({ threads: { isLoading: state.busy, isLoadingMore: false } }),
}));
const client = {
  threads: () => ({
    reload: state.reload,
    getState: () => ({
      threadItems: state.items,
      threadIds: state.items.map((item) => item.id),
    }),
  }),
};
const data = {
  items: [
    {
      conversation_id: 1,
      conversation_title: "History",
      create_time: 1,
      update_time: 1,
      last_activity_time: 10,
    },
  ],
  metadata: { total: 1, today: 1, last_7_days: 0, older: 0 },
  next_cursor: null,
};
const clients: QueryClient[] = [];
afterEach(() => {
  clients.splice(0).forEach((value) => value.clear());
  state.busy = false;
});
function setup() {
  const query = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  clients.push(query);
  state.reload.mockReset().mockImplementation(async () => {
    state.items = data.items.map((row) => ({
      id: String(row.conversation_id),
      remoteId: String(row.conversation_id),
      title: row.conversation_title,
      custom: { lastMessageAt: new Date(row.last_activity_time).toISOString() },
    }));
  });
  return renderHook(
    ({ scope }: { scope: string | null }) =>
      useConversationActivitySync(scope, "workbench"),
    {
      initialProps: { scope: "owner" as string | null },
      wrapper: ({ children }: PropsWithChildren) => (
        <QueryClientProvider client={query}>{children}</QueryClientProvider>
      ),
    }
  );
}

it("can render without browser globals during server rendering", () => {
  const query = new QueryClient();
  function Probe() {
    useConversationActivitySync("owner", "workbench");
    return null;
  }
  vi.stubGlobal("document", undefined);
  try {
    expect(() =>
      renderToString(
        <QueryClientProvider client={query}>
          <Probe />
        </QueryClientProvider>
      )
    ).not.toThrow();
  } finally {
    vi.unstubAllGlobals();
    query.clear();
  }
});

it("refreshes only changed metadata and refetches immediately after a local run", async () => {
  state.items = [];
  const get = vi.spyOn(conversationService, "getList").mockResolvedValue(data);
  setup();
  await waitFor(() => expect(state.reload).toHaveBeenCalledTimes(1));
  act(() => state.runEnd?.());
  await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
  expect(state.reload).toHaveBeenCalledTimes(1);
});

it("does not reload an already-current list on mount or after remount", async () => {
  state.items = [
    {
      id: "1",
      remoteId: "1",
      title: "History",
      custom: { lastMessageAt: new Date(10).toISOString() },
    },
  ];
  const get = vi.spyOn(conversationService, "getList").mockResolvedValue(data);
  const first = setup();
  await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
  expect(state.reload).not.toHaveBeenCalled();
  first.unmount();
  setup();
  await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
  expect(state.reload).not.toHaveBeenCalled();
});

it("coalesces focus/reconnect while a request is pending and stops after unmount", async () => {
  let resolve!: (value: typeof data) => void;
  const get = vi.spyOn(conversationService, "getList").mockReturnValue(
    new Promise((done) => {
      resolve = done;
    })
  );
  const view = setup();
  await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
  act(() => {
    window.dispatchEvent(new Event("focus"));
    window.dispatchEvent(new Event("online"));
  });
  expect(get).toHaveBeenCalledTimes(1);
  view.unmount();
  await act(async () => resolve(data));
  expect(state.reload).not.toHaveBeenCalled();
});

it("does not fetch for an anonymous scope or a hidden document", async () => {
  let visibility: DocumentVisibilityState = "hidden";
  vi.spyOn(document, "visibilityState", "get").mockImplementation(
    () => visibility
  );
  const get = vi.spyOn(conversationService, "getList").mockResolvedValue(data);
  const view = setup();
  expect(get).not.toHaveBeenCalled();
  view.rerender({ scope: null });
  visibility = "visible";
  act(() => document.dispatchEvent(new Event("visibilitychange")));
  expect(get).not.toHaveBeenCalled();
  view.rerender({ scope: "owner" });
  await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
});

it("retains the confirmed list on fetch failure and recovers on focus", async () => {
  state.items = [];
  const get = vi
    .spyOn(conversationService, "getList")
    .mockRejectedValueOnce(new Error("network"))
    .mockResolvedValue(data);
  setup();
  await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
  expect(state.reload).not.toHaveBeenCalled();
  act(() => window.dispatchEvent(new Event("focus")));
  await waitFor(() => expect(state.reload).toHaveBeenCalledTimes(1));
});
