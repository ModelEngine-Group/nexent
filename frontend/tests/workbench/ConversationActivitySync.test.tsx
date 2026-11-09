// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, cleanup, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { PropsWithChildren } from "react";
import { renderToString } from "react-dom/server";
import { useConversationActivitySync } from "@/hooks/chat/useConversationActivitySync";
import { conversationService } from "@/services/conversationService";

const state = vi.hoisted(() => ({
  busy: false,
  reload: vi.fn<() => Promise<void>>(),
  runEnd: undefined as undefined | (() => void),
}));
vi.mock("@assistant-ui/react", () => ({
  useAui: () => runtime,
  useAuiEvent: (_event: unknown, callback: () => void) => {
    state.runEnd = callback;
  },
  useAuiState: (selector: (value: unknown) => unknown) =>
    selector({ threads: { isLoading: state.busy, isLoadingMore: false } }),
}));
const runtime = {
  threads: () => ({
    reload: state.reload,
    getState: () => ({
      isLoading: state.busy,
      isLoadingMore: false,
      threadItems: [],
      threadIds: [],
    }),
  }),
};
const clients: QueryClient[] = [];
let visible: DocumentVisibilityState;
let online: boolean;
beforeEach(() => {
  visible = "visible";
  online = true;
  state.busy = false;
  state.reload.mockReset().mockResolvedValue();
  vi.spyOn(document, "visibilityState", "get").mockImplementation(
    () => visible
  );
  vi.spyOn(navigator, "onLine", "get").mockImplementation(() => online);
  vi.spyOn(conversationService, "getList").mockResolvedValue({
    items: [],
    metadata: { total: 0, today: 0, last_7_days: 0, older: 0 },
    next_cursor: null,
  });
  vi.useFakeTimers();
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((c) => c.clear());
  vi.useRealTimers();
});
interface Props {
  scope: string | null;
  type: "workbench" | "agent_chat";
  serverConversationIds?: ReadonlyMap<string, string>;
  generatedTitles?: ReadonlyMap<string, string>;
}
function setup(props: Partial<Props> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  clients.push(client);
  return renderHook(
    ({ scope, type, ...changes }: Props) =>
      useConversationActivitySync(scope, type, changes),
    {
      initialProps: { scope: "owner", type: "workbench", ...props } as Props,
      wrapper: ({ children }: PropsWithChildren) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    }
  );
}
async function advance(ms = 100) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}
function foreground() {
  window.dispatchEvent(new Event("focus"));
  window.dispatchEvent(new Event("online"));
  document.dispatchEvent(new Event("visibilitychange"));
}

it("can render without browser globals during server rendering", () => {
  const client = new QueryClient();
  function Probe() {
    useConversationActivitySync("owner", "workbench");
    return null;
  }
  vi.stubGlobal("document", undefined);
  try {
    expect(() =>
      renderToString(
        <QueryClientProvider client={client}>
          <Probe />
        </QueryClientProvider>
      )
    ).not.toThrow();
  } finally {
    vi.unstubAllGlobals();
    client.clear();
  }
});

it("adds no duplicate initial list read and makes no periodic request while idle for sixty seconds", async () => {
  setup();
  await advance(60_000);
  expect(conversationService.getList).not.toHaveBeenCalled();
  expect(state.reload).not.toHaveBeenCalled();
});

it("coalesces terminal run events and reloads the runtime without a duplicate first-page probe", async () => {
  setup();
  act(() => {
    state.runEnd?.();
    state.runEnd?.();
  });
  await advance();
  expect(state.reload).toHaveBeenCalledTimes(1);
  expect(conversationService.getList).not.toHaveBeenCalled();
  await advance(60_000);
  expect(state.reload).toHaveBeenCalledTimes(1);
});

it("coalesces focus, visibility and reconnect and ignores ordinary pointer interactions", async () => {
  setup();
  act(foreground);
  await advance();
  expect(state.reload).toHaveBeenCalledTimes(1);
  act(() => {
    document.dispatchEvent(new Event("pointerdown"));
    document.dispatchEvent(new Event("focusin"));
  });
  await advance(60_000);
  expect(state.reload).toHaveBeenCalledTimes(1);
});

it("observes first persisted identity and a late saved title while ignoring identical map contents", async () => {
  const props: Props = { scope: "owner", type: "workbench" };
  const { rerender } = setup(props);
  rerender({ ...props, serverConversationIds: new Map([["local", "42"]]) });
  await advance();
  expect(state.reload).toHaveBeenCalledTimes(1);
  rerender({ ...props, serverConversationIds: new Map([["local", "42"]]) });
  await advance();
  expect(state.reload).toHaveBeenCalledTimes(1);
  rerender({
    ...props,
    serverConversationIds: new Map([["local", "42"]]),
    generatedTitles: new Map([["local", "Saved late title"]]),
  });
  await advance();
  expect(state.reload).toHaveBeenCalledTimes(2);
});

it("does not treat an unpersisted draft mapping as a saved history", async () => {
  const { rerender } = setup();
  rerender({
    scope: "owner",
    type: "workbench",
    serverConversationIds: new Map([["local", "workbench-draft:local"]]),
  });
  await advance();
  expect(state.reload).not.toHaveBeenCalled();
});

it("keeps one trailing operation refresh but ignores duplicate foreground events during a pending read", async () => {
  let finish!: () => void;
  state.reload.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      })
  );
  setup();
  act(foreground);
  await advance();
  expect(state.reload).toHaveBeenCalledTimes(1);
  act(foreground);
  await advance();
  expect(state.reload).toHaveBeenCalledTimes(1);
  act(() => {
    state.runEnd?.();
    state.runEnd?.();
  });
  await advance();
  expect(state.reload).toHaveBeenCalledTimes(1);
  await act(async () => finish());
  await advance();
  expect(state.reload).toHaveBeenCalledTimes(2);
});

it("waits for an existing pagination load instead of dropping the event", async () => {
  state.busy = true;
  const { rerender } = setup();
  act(() => state.runEnd?.());
  await advance();
  expect(state.reload).not.toHaveBeenCalled();
  state.busy = false;
  rerender({ scope: "owner", type: "workbench" });
  await advance();
  expect(state.reload).toHaveBeenCalledTimes(1);
});

it("keeps hidden or offline changes pending until foreground and network recovery", async () => {
  setup();
  visible = "hidden";
  act(() => {
    state.runEnd?.();
    foreground();
  });
  await advance();
  expect(state.reload).not.toHaveBeenCalled();
  visible = "visible";
  online = false;
  act(foreground);
  await advance();
  expect(state.reload).not.toHaveBeenCalled();
  online = true;
  act(foreground);
  await advance();
  expect(state.reload).toHaveBeenCalledTimes(1);
});

it("does not refresh anonymous or Agent-chat scopes", async () => {
  const { rerender } = setup({ scope: null });
  act(() => {
    state.runEnd?.();
    foreground();
  });
  await advance();
  rerender({ scope: "owner", type: "agent_chat" });
  act(() => {
    state.runEnd?.();
    foreground();
  });
  await advance();
  expect(state.reload).not.toHaveBeenCalled();
});

it("discards queued work when the identity changes or the sidebar unmounts", async () => {
  const { rerender, unmount } = setup();
  act(() => state.runEnd?.());
  rerender({ scope: "other-tenant", type: "workbench" });
  await advance();
  expect(state.reload).not.toHaveBeenCalled();
  act(() => state.runEnd?.());
  unmount();
  await advance();
  act(foreground);
  await advance();
  expect(state.reload).not.toHaveBeenCalled();
});

it("does not schedule another identity's pending changes when an old request settles", async () => {
  let finish!: () => void;
  state.reload.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      })
  );
  const { rerender } = setup();
  act(() => state.runEnd?.());
  await advance();
  act(() => state.runEnd?.());
  rerender({ scope: "other-tenant", type: "workbench" });
  await act(async () => finish());
  await advance();
  expect(state.reload).toHaveBeenCalledTimes(1);
  act(foreground);
  await advance();
  expect(state.reload).toHaveBeenCalledTimes(2);
});

it("does not retry a failed reload until another event", async () => {
  state.reload.mockRejectedValueOnce(new Error("History unavailable"));
  setup();
  act(() => state.runEnd?.());
  await advance();
  expect(state.reload).toHaveBeenCalledTimes(1);
  await advance(60_000);
  expect(state.reload).toHaveBeenCalledTimes(1);
  act(foreground);
  await advance();
  expect(state.reload).toHaveBeenCalledTimes(2);
});
