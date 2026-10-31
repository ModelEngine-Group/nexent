// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, renderHook, waitFor } from "@testing-library/react";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { useScanToolList } from "@/hooks/agent/useScanToolList";
import { updateToolList } from "@/services/mcpService";

vi.mock("@/services/mcpService", () => ({ updateToolList: vi.fn() }));

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

describe("tool catalog scan", () => {
  it("discovers newly deployed tools before reloading the catalog and active tag caches", async () => {
    const { client, wrapper } = setup();
    let catalog = ["tavily_search"];
    let completeScan!: () => void;
    const scanFinished = new Promise<void>((resolve) => {
      completeScan = resolve;
    });
    vi.mocked(updateToolList).mockImplementation(async () => {
      await scanFinished;
      catalog = [...catalog, "deepseek_search"];
      return { success: true, data: {}, message: "ok" };
    });
    client.setQueryData(["resourceTagMatches", "tool", ["1"]], ["1"]);
    client.setQueryData(["resourceTagAssignments", "tool", "tenant"], {});
    client.setQueryData(["resourceTagMatches", "agent"], ["agent"]);
    const loadCatalog = vi.fn(async () => catalog);
    const { result } = renderHook(
      () => ({
        scan: useScanToolList(),
        tools: useQuery({ queryKey: ["tools"], queryFn: loadCatalog }),
      }),
      { wrapper }
    );
    await waitFor(() =>
      expect(result.current.tools.data).toEqual(["tavily_search"])
    );
    act(() => result.current.scan.mutate());
    await waitFor(() => expect(result.current.scan.isPending).toBe(true));
    expect(loadCatalog).toHaveBeenCalledTimes(1);
    await act(async () => completeScan());
    await waitFor(() => expect(result.current.scan.isSuccess).toBe(true));
    expect(result.current.tools.data).toEqual([
      "tavily_search",
      "deepseek_search",
    ]);
    expect(
      client.getQueryState(["resourceTagMatches", "tool", ["1"]])?.isInvalidated
    ).toBe(true);
    expect(
      client.getQueryState(["resourceTagAssignments", "tool", "tenant"])
        ?.isInvalidated
    ).toBe(true);
    expect(
      client.getQueryState(["resourceTagMatches", "agent"])?.isInvalidated
    ).toBe(false);
    client.clear();
  });

  it.each(["server", "network"])(
    "reports %s failures and retains the current catalog",
    async (failure) => {
      const { client, wrapper } = setup();
      client.setQueryData(["tools"], ["tavily_search"]);
      if (failure === "server") {
        vi.mocked(updateToolList).mockResolvedValue({
          success: false,
          data: null,
          message: "Scan failed",
        });
      } else {
        vi.mocked(updateToolList).mockRejectedValue(
          new Error("Network unavailable")
        );
      }
      const { result } = renderHook(() => useScanToolList(), { wrapper });
      await act(async () => {
        await expect(result.current.mutateAsync()).rejects.toThrow(
          failure === "server" ? "Scan failed" : "Network unavailable"
        );
      });
      await waitFor(() => expect(result.current.isError).toBe(true));
      expect(client.getQueryData(["tools"])).toEqual(["tavily_search"]);
      expect(client.getQueryState(["tools"])?.isInvalidated).toBe(false);
      client.clear();
    }
  );
});
