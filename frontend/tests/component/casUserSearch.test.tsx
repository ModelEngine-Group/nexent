// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";
import { expect, it, vi } from "vitest";

import { useUserList } from "@/hooks/user/useUserList";

const session = vi.hoisted(() => ({ provider: "cas", list: vi.fn() }));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { authProvider: session.provider } }),
}));
vi.mock("@/services/userService", () => ({ listUsers: session.list }));

it("isolates CAS/local search caches while retaining existing request arguments", async () => {
  session.provider = "cas";
  session.list.mockImplementation(async () => ({
    users:
      session.provider === "cas"
        ? [{ id: "a", username: "alpha@test", cas_username: "Bob" }]
        : [],
    total: session.provider === "cas" ? 1 : 0,
  }));
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const filters = { search: "Bob", roles: ["USER"], groupIds: [7] };
  const { result, rerender, unmount } = renderHook(
    () => useUserList("tenant", 1, 10, filters),
    { wrapper }
  );
  await waitFor(() => expect(result.current.data?.total).toBe(1));
  session.provider = "local";
  rerender();
  expect(result.current.data).toBeUndefined();
  await waitFor(() => expect(result.current.data?.total).toBe(0));
  expect(session.list.mock.calls).toEqual([
    ["tenant", 1, 10, filters],
    ["tenant", 1, 10, filters],
  ]);
  expect(
    client
      .getQueryCache()
      .getAll()
      .map((query) => query.queryKey.at(-1))
  ).toEqual(["cas", "local"]);
  unmount();
  client.clear();
});
