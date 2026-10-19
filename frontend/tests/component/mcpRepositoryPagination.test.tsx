// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { McpTransportType } from "@/const/mcpTools";
import { useMcpCommunityBrowser } from "@/hooks/mcpTools/useMcpCommunityBrowser";
import {
  fetchCommunityMcpCards,
  fetchCommunityMcpTagStats,
} from "@/services/mcpToolsService";

vi.mock("@/services/mcpToolsService", () => ({
  fetchCommunityMcpCards: vi.fn(),
  fetchCommunityMcpTagStats: vi.fn(async () => ({ success: true, data: [] })),
}));

const clients: QueryClient[] = [];
beforeEach(() => vi.mocked(fetchCommunityMcpCards).mockReset());
afterEach(() => {
  for (const client of clients.splice(0)) client.clear();
});

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  return renderHook(() => useMcpCommunityBrowser(true, 12), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

const response = (total: number) => ({
  success: true as const,
  data: { items: [], nextCursor: null, total },
});

describe("MCP repository page transitions", () => {
  it("retains page two while its response is pending and after a request error", async () => {
    let rejectNext!: (error: Error) => void;
    vi.mocked(fetchCommunityMcpCards)
      .mockResolvedValueOnce(response(25))
      .mockImplementationOnce(
        () =>
          new Promise((_, reject) => {
            rejectNext = reject;
          })
      );
    const { result } = setup();
    await waitFor(() => expect(result.current.total).toBe(25));
    act(() => result.current.setPage(2));
    await waitFor(() =>
      expect(fetchCommunityMcpCards).toHaveBeenLastCalledWith(
        expect.objectContaining({ page: 2, limit: 12 })
      )
    );
    expect(result.current.page).toBe(2);
    expect(result.current.total).toBe(0);
    expect(result.current.loading).toBe(true);
    await act(async () => rejectNext(new Error("Network unavailable")));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.page).toBe(2);
    expect(result.current.error).toEqual(new Error("Network unavailable"));
  });

  it("retries the failed page with the same search and filters", async () => {
    vi.mocked(fetchCommunityMcpCards).mockResolvedValue(response(25));
    const { result } = setup();
    await waitFor(() => expect(result.current.total).toBe(25));
    act(() => {
      result.current.updateFilter("tag", "analytics");
      result.current.updateFilter("transport", McpTransportType.SSE);
      result.current.updateFilter("search", "tool");
    });
    await waitFor(() =>
      expect(fetchCommunityMcpCards).toHaveBeenLastCalledWith(
        expect.objectContaining({
          search: "tool",
          transportType: "sse",
          tag: "analytics",
        })
      )
    );
    vi.mocked(fetchCommunityMcpCards).mockRejectedValueOnce(
      new Error("Network unavailable")
    );
    act(() => result.current.setPage(2));
    await waitFor(() => expect(result.current.error).toBeInstanceOf(Error));
    const failedParameters = vi.mocked(fetchCommunityMcpCards).mock
      .lastCall?.[0];
    expect(failedParameters).toEqual({
      search: "tool",
      transportType: "sse",
      tag: "analytics",
      page: 2,
      limit: 12,
    });
    await act(async () => {
      await result.current.refetch();
    });
    await waitFor(() => expect(result.current.error).toBeNull());
    expect(result.current.page).toBe(2);
    expect(result.current.total).toBe(25);
    expect(fetchCommunityMcpCards).toHaveBeenLastCalledWith(failedParameters);
  });

  it("clamps an out-of-range page only after a successful authoritative response", async () => {
    vi.mocked(fetchCommunityMcpCards)
      .mockReset()
      .mockResolvedValueOnce(response(25))
      .mockResolvedValueOnce(response(5))
      .mockResolvedValue(response(5));
    const { result } = setup();
    await waitFor(() => expect(result.current.total).toBe(25));
    act(() => result.current.setPage(3));
    await waitFor(() => expect(result.current.page).toBe(1));
    expect(fetchCommunityMcpCards).toHaveBeenCalledWith(
      expect.objectContaining({ page: 3, limit: 12 })
    );
    expect(fetchCommunityMcpTagStats).toHaveBeenCalled();
  });
});
