// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useAgentBulkDelete } from "@/hooks/agent/useAgentBulkDelete";
import { deleteAgent } from "@/services/agentConfigService";
import type { Agent } from "@/types/agentConfig";

vi.mock("@/services/agentConfigService", () => ({ deleteAgent: vi.fn() }));

const remove = vi.mocked(deleteAgent);
const clients: QueryClient[] = [];
const agent = (id: string, permission: Agent["permission"] = "EDIT") =>
  ({ id, name: `Agent ${id}`, permission }) as Agent;

function setup() {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  clients.push(client);
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const hook = renderHook(() => useAgentBulkDelete(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
  return { ...hook, invalidate };
}

afterEach(() => {
  clients.splice(0).forEach((client) => client.clear());
  remove.mockReset();
});

describe("agent bulk deletion", () => {
  it("deletes every eligible agent and invalidates both list caches", async () => {
    remove.mockResolvedValue({ success: true, message: "Deleted" });
    const { result, invalidate } = setup();
    const agents = [agent("1"), agent("2")];
    await act(async () => {
      expect(await result.current.mutateAsync(agents)).toEqual({
        deleted: agents,
        failed: [],
      });
    });
    expect(remove.mock.calls).toEqual([[1], [2]]);
    expect(invalidate.mock.calls).toEqual([
      [{ queryKey: ["agents"] }],
      [{ queryKey: ["publishedAgentsList"] }],
    ]);
  });

  it("keeps API failures separate from successful deletions and continues", async () => {
    remove
      .mockResolvedValueOnce({ success: false, message: "Deletion refused" })
      .mockResolvedValueOnce({ success: true, message: "Deleted" });
    const { result } = setup();
    const agents = [agent("1"), agent("2")];
    await act(async () => {
      expect(await result.current.mutateAsync(agents)).toEqual({
        deleted: [agents[1]],
        failed: [agents[0]],
      });
    });
    expect(remove.mock.calls).toEqual([[1], [2]]);
  });

  it("records a rejected request as failure and still deletes later agents", async () => {
    remove
      .mockRejectedValueOnce(new Error("Request failed"))
      .mockResolvedValueOnce({ success: true, message: "Deleted" });
    const { result } = setup();
    const agents = [agent("1"), agent("2")];
    await act(async () => {
      expect(await result.current.mutateAsync(agents)).toEqual({
        deleted: [agents[1]],
        failed: [agents[0]],
      });
    });
    expect(remove.mock.calls).toEqual([[1], [2]]);
  });

  it("never sends read-only or invalid identifiers to the delete API", async () => {
    remove.mockResolvedValue({ success: true, message: "Deleted" });
    const { result } = setup();
    const forbidden = [
      agent("1", "READ_ONLY"),
      ...["0", "-1", "1.5", "abc", ""].map((id) => agent(id)),
    ];
    const eligible = agent("2");
    await act(async () => {
      expect(
        await result.current.mutateAsync([...forbidden, eligible])
      ).toEqual({
        deleted: [eligible],
        failed: forbidden,
      });
    });
    expect(remove).toHaveBeenCalledExactlyOnceWith(2);
  });

  it("handles an empty selection without a delete request", async () => {
    const { result } = setup();
    await act(async () => {
      expect(await result.current.mutateAsync([])).toEqual({
        deleted: [],
        failed: [],
      });
    });
    expect(remove).not.toHaveBeenCalled();
  });

  it("stays pending until the outstanding deletion completes", async () => {
    let finish!: (value: Awaited<ReturnType<typeof deleteAgent>>) => void;
    remove.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
    const { result } = setup();
    act(() => result.current.mutate([agent("1")]));
    await waitFor(() => expect(result.current.isPending).toBe(true));
    expect(remove).toHaveBeenCalledExactlyOnceWith(1);
    await act(async () => finish({ success: true, message: "Deleted" }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ deleted: [agent("1")], failed: [] });
  });
});
