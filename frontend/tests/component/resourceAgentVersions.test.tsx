// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { useResourceAgentVersions } from "@/hooks/agent/useResourceAgentVersions";
import { fetchAgentVersionList } from "@/services/agentVersionService";
import type { AgentVersion } from "@/services/agentVersionService";

vi.mock("@/services/agentVersionService", () => ({
  fetchAgentVersionList: vi.fn(),
}));

const response = {
  success: true,
  data: {
    items: [{ version_no: 3, version_name: "Release three" } as AgentVersion],
    total: 1,
  },
  message: "",
};

function setup(tenant = "a") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const hook = renderHook(
    ({ tenantId }) => useResourceAgentVersions(tenantId),
    { initialProps: { tenantId: tenant }, wrapper }
  );
  return { ...hook, client };
}

describe("resource Agent version history", () => {
  it("loads on demand and reuses fresh cached responses", async () => {
    vi.mocked(fetchAgentVersionList).mockResolvedValue(response);
    const hook = setup();
    expect(fetchAgentVersionList).not.toHaveBeenCalled();
    await act(() => hook.result.current.loadVersions(7));
    expect(fetchAgentVersionList).toHaveBeenCalledExactlyOnceWith(7, "a");
    expect(hook.result.current.agentVersions.get(7)).toEqual(
      response.data.items
    );
    await act(() => hook.result.current.loadVersions(7));
    expect(fetchAgentVersionList).toHaveBeenCalledTimes(1);
    hook.unmount();
    hook.client.clear();
  });

  it("deduplicates concurrent opens and clears loading", async () => {
    let resolve!: (value: typeof response) => void;
    vi.mocked(fetchAgentVersionList).mockReturnValue(
      new Promise((done) => {
        resolve = done;
      })
    );
    const hook = setup();
    let first!: Promise<void>;
    let second!: Promise<void>;
    act(() => {
      first = hook.result.current.loadVersions(7);
      second = hook.result.current.loadVersions(7);
    });
    expect(hook.result.current.loadingVersions.get(7)).toBe(true);
    await act(async () => {
      resolve(response);
      await Promise.all([first, second]);
    });
    expect(fetchAgentVersionList).toHaveBeenCalledTimes(1);
    expect(hook.result.current.loadingVersions.get(7)).toBe(false);
    hook.unmount();
    hook.client.clear();
  });

  it("ignores stale responses after switching tenants", async () => {
    let resolve!: (value: typeof response) => void;
    vi.mocked(fetchAgentVersionList)
      .mockReturnValueOnce(
        new Promise((done) => {
          resolve = done;
        })
      )
      .mockResolvedValue(response);
    const hook = setup();
    let pending!: Promise<void>;
    act(() => {
      pending = hook.result.current.loadVersions(7);
    });
    hook.rerender({ tenantId: "b" });
    expect(hook.result.current.agentVersions.size).toBe(0);
    await act(async () => {
      resolve(response);
      await pending;
    });
    expect(hook.result.current.agentVersions.size).toBe(0);
    await act(() => hook.result.current.loadVersions(7));
    expect(fetchAgentVersionList).toHaveBeenLastCalledWith(7, "b");
    hook.unmount();
    hook.client.clear();
  });

  it("allows retry after failure and preserves empty history", async () => {
    vi.mocked(fetchAgentVersionList)
      .mockResolvedValueOnce({
        success: false,
        data: { items: [], total: 0 },
        message: "unavailable",
      })
      .mockResolvedValue({
        success: true,
        data: { items: [], total: 0 },
        message: "",
      });
    const hook = setup();
    await act(async () => {
      await expect(hook.result.current.loadVersions(7)).rejects.toThrow(
        "unavailable"
      );
    });
    expect(hook.result.current.loadingVersions.get(7)).toBe(false);
    expect(hook.result.current.agentVersions.has(7)).toBe(false);
    await act(() => hook.result.current.loadVersions(7));
    expect(hook.result.current.agentVersions.get(7)).toEqual([]);
    hook.unmount();
    hook.client.clear();
  });
});
