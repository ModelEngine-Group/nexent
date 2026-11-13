// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { useCreatorHistories } from "@/hooks/chat/useCreatorHistories";

const state = vi.hoisted(() => ({
  user: { id: "u", tenantId: "t" },
  request: vi.fn(),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: state.user }),
}));
vi.mock("@/services/conversationService", () => ({
  conversationService: { getCreatorHistories: state.request },
}));

function page(id: number, total = 2) {
  return {
    items: [
      {
        conversation_id: id,
        conversation_title: String(id),
        create_time: 0,
        update_time: 0,
      },
    ],
    total,
  };
}
function setup(target: number | null = 42, kind: "agent" | "skill" = "agent") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return {
    client,
    ...renderHook(({ id }) => useCreatorHistories(kind, id), {
      initialProps: { id: target },
      wrapper,
    }),
  };
}
beforeEach(() => {
  state.user = { id: "u", tenantId: "t" };
  state.request.mockReset();
});

it("loads all target histories by pages and reports the server count", async () => {
  state.request.mockResolvedValueOnce(page(12)).mockResolvedValueOnce(page(11));
  const view = setup();
  await waitFor(() => expect(view.result.current.total).toBe(2));
  expect(state.request).toHaveBeenCalledWith("agent", 42, 0);
  await act(async () => {
    await view.result.current.loadMore();
  });
  await waitFor(() =>
    expect(
      view.result.current.items.map((item) => item.conversation_id)
    ).toEqual([12, 11])
  );
  expect(state.request).toHaveBeenLastCalledWith("agent", 42, 1);
  expect(view.result.current.hasMore).toBe(false);
  view.unmount();
  view.client.clear();
});

it("separates query data when resource, user or tenant changes", async () => {
  state.request.mockImplementation(async (_kind, id) => page(id, 1));
  const view = setup();
  await waitFor(() =>
    expect(view.result.current.items[0]?.conversation_id).toBe(42)
  );
  view.rerender({ id: 99 });
  await waitFor(() =>
    expect(view.result.current.items[0]?.conversation_id).toBe(99)
  );
  state.user = { id: "other", tenantId: "other-tenant" };
  state.request.mockResolvedValue(page(100, 1));
  view.rerender({ id: 99 });
  await waitFor(() =>
    expect(view.result.current.items[0]?.conversation_id).toBe(100)
  );
  expect(
    view.client.getQueryData(["creator-histories", "u", "t", "agent", 42])
  ).toBeDefined();
  expect(
    view.client.getQueryData([
      "creator-histories",
      "other",
      "other-tenant",
      "agent",
      99,
    ])
  ).toBeDefined();
  view.unmount();
  view.client.clear();
});

it("does not query before a target exists and supports retry after a failure", async () => {
  const view = setup(null);
  expect(view.result.current.total).toBe(0);
  await act(async () => {
    await view.result.current.refetch();
  });
  expect(state.request).not.toHaveBeenCalled();
  state.request.mockRejectedValueOnce(new Error("offline"));
  view.rerender({ id: 42 });
  await waitFor(() => expect(view.result.current.failed).toBe(true));
  state.request.mockResolvedValue(page(12, 1));
  await act(async () => {
    await view.result.current.refetch();
  });
  await waitFor(() => expect(view.result.current.failed).toBe(false));
  expect(view.result.current.total).toBe(1);
  view.unmount();
  view.client.clear();
});

it("shows zero without querying an unsaved skill and loads its records after an ID is known", async () => {
  const view = setup(null, "skill");
  expect(view.result.current.total).toBe(0);
  await act(async () => {
    await view.result.current.refetch();
  });
  expect(state.request).not.toHaveBeenCalled();
  state.request.mockResolvedValue(page(12, 1));
  view.rerender({ id: 8 });
  await waitFor(() => expect(view.result.current.total).toBe(1));
  expect(state.request).toHaveBeenCalledWith("skill", 8, 0);
  expect(
    view.client.getQueryData(["creator-histories", "u", "t", "skill", 8])
  ).toBeDefined();
  view.unmount();
  view.client.clear();
});
