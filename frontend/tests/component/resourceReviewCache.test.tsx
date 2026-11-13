// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useResourceReviews } from "@/hooks/resourceReview/useResourceReviews";
import { decideResourceReview } from "@/services/resourceReviewService";

const auth = vi.hoisted(() => ({
  id: "actor-a",
  tenantId: "tenant-a",
  role: "ADMIN",
  granted: true,
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    user: auth,
    isAuthzReady: true,
    canAccessRoute: () => auth.granted,
  }),
}));
vi.mock("@/services/resourceReviewService", () => ({
  fetchResourceReviews: vi.fn(async () => ({
    items: [],
    pagination: { total: 0, total_pages: 0 },
  })),
  fetchResourceReview: vi.fn(async () => ({ review_id: "41" })),
  decideResourceReview: vi.fn(),
}));
const clients: QueryClient[] = [];
afterEach(() => {
  clients.splice(0).forEach((client) => client.clear());
  vi.clearAllMocks();
  auth.granted = true;
  auth.id = "actor-a";
});
function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  const hook = renderHook(
    () =>
      useResourceReviews({
        type: "all",
        status: "all",
        search: "",
        page: 1,
        page_size: 10,
      }),
    {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    }
  );
  return { client, ...hook };
}
describe("unified review cache boundaries", () => {
  it("invalidates review and warehouse data after a lost decision response without retrying", async () => {
    vi.mocked(decideResourceReview).mockRejectedValue(
      new Error("Response lost")
    );
    const { client, result } = setup();
    client.setQueryData(["skillRepository", "page"], {
      status: "pending_review",
    });
    client.setQueryData(["agents", "page"], { status: "pending_review" });
    client.setQueryData(["unrelated"], { retained: true });
    await act(async () => {
      await expect(
        result.current.decision.mutateAsync({
          type: "skill",
          id: "9007199254740993",
          decision: "approve",
          reason: "",
        })
      ).rejects.toThrow("Response lost");
    });
    expect(decideResourceReview).toHaveBeenCalledTimes(1);
    expect(
      client.getQueryState(["skillRepository", "page"])?.isInvalidated
    ).toBe(true);
    expect(client.getQueryState(["agents", "page"])?.isInvalidated).toBe(true);
    expect(client.getQueryState(["unrelated"])?.isInvalidated).toBe(false);
  });
  it("partitions list data by authenticated identity", async () => {
    const { client, result, rerender } = setup();
    await waitFor(() => expect(result.current.list.isSuccess).toBe(true));
    auth.id = "actor-b";
    rerender();
    await waitFor(() => expect(result.current.list.isSuccess).toBe(true));
    const identities = client
      .getQueryCache()
      .getAll()
      .filter((query) => query.queryKey[0] === "resourceReviews")
      .map((query) => query.queryKey[1]);
    expect(identities).toEqual(expect.arrayContaining(["actor-a", "actor-b"]));
  });
  it("does not fetch list data without the new URL permission", () => {
    auth.granted = false;
    const { result } = setup();
    expect(result.current.list.fetchStatus).toBe("idle");
  });
});
