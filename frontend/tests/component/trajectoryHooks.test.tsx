// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { trajectoryService } from "@/services/trajectoryService";
import { useTrajectoryRecords } from "@/hooks/trajectory/useTrajectoryRecords";
import { useTrajectoryCleanup } from "@/hooks/trajectory/useTrajectoryCleanup";
import type {
  CleanupResult,
  RecordsPage,
  RecordsRequest,
} from "@/types/trajectory";
import { recordsPage } from "./trajectoryFixtures";

vi.mock("@/services/trajectoryService", () => ({
  trajectoryService: { records: vi.fn(), cleanup: vi.fn() },
}));
const api = vi.mocked(trajectoryService);
function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      {children}
    </QueryClientProvider>
  );
}
const batch = (overrides: Partial<CleanupResult> = {}): CleanupResult => ({
  cutoff_at: "fixed",
  scanned_runs: 2,
  deleted_runs: 1,
  deleted_bytes: 100,
  skipped_active: 0,
  pending_runs: 0,
  failed_runs: 0,
  next_cursor: null,
  done: true,
  ...overrides,
});
beforeEach(() => {
  vi.clearAllMocks();
  api.records.mockResolvedValue(recordsPage());
});

describe("trajectory query membership", () => {
  it("retains query_id for page/sort, resets on filter and explicit refresh", async () => {
    const hook = renderHook(
      ({ params }: { params: RecordsRequest }) =>
        useTrajectoryRecords("actor", params),
      {
        initialProps: { params: { page: 1, tenant_id: "t" } as RecordsRequest },
        wrapper,
      }
    );
    await waitFor(() => expect(hook.result.current.isSuccess).toBe(true));
    hook.rerender({
      params: { page: 2, tenant_id: "t", sort_by: "duration_ms" },
    });
    await waitFor(() => expect(api.records).toHaveBeenCalledTimes(2));
    expect(api.records.mock.calls[1][0].query_id).toBe("signed-query");
    hook.rerender({ params: { page: 1, tenant_id: "other" } });
    await waitFor(() => expect(api.records).toHaveBeenCalledTimes(3));
    expect(api.records.mock.calls[2][0].query_id).toBeUndefined();
    act(() => hook.result.current.refresh());
    await waitFor(() => expect(api.records).toHaveBeenCalledTimes(4));
    expect(api.records.mock.calls[3][0].query_id).toBeUndefined();
  });
  it("aborts stale requests and never displays their late result", async () => {
    let finish!: (page: RecordsPage) => void;
    api.records.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
    const hook = renderHook(
      ({ tenant }) => useTrajectoryRecords("actor", { tenant_id: tenant }),
      { initialProps: { tenant: "old" }, wrapper }
    );
    await waitFor(() => expect(api.records).toHaveBeenCalledTimes(1));
    const oldSignal = api.records.mock.calls[0][1]!;
    hook.rerender({ tenant: "new" });
    await waitFor(() => expect(hook.result.current.isSuccess).toBe(true));
    expect(oldSignal.aborted).toBe(true);
    await act(async () => finish(recordsPage("stale")));
    expect(hook.result.current.data?.query_id).toBe("signed-query");
  });
  it("does not refresh on window focus", async () => {
    const hook = renderHook(() => useTrajectoryRecords("actor", {}), {
      wrapper,
    });
    await waitFor(() => expect(hook.result.current.isSuccess).toBe(true));
    act(() => window.dispatchEvent(new Event("focus")));
    expect(api.records).toHaveBeenCalledTimes(1);
  });
});

describe("trajectory cleanup batches", () => {
  it("requires an explicit start, follows cursor, and totals real batch results", async () => {
    api.cleanup
      .mockResolvedValueOnce(batch({ done: false, next_cursor: "next" }))
      .mockResolvedValueOnce(batch({ pending_runs: 1 }));
    const complete = vi.fn();
    const hook = renderHook(() => useTrajectoryCleanup(complete));
    expect(api.cleanup).not.toHaveBeenCalled();
    await act(async () => hook.result.current.start(7));
    expect(api.cleanup.mock.calls[1][1]).toBe("next");
    expect(hook.result.current.result).toMatchObject({
      deleted_runs: 2,
      deleted_bytes: 200,
      pending_runs: 1,
    });
    expect(complete).toHaveBeenCalledOnce();
  });
  it("stops issuing batches after cancellation even if transport resolves late", async () => {
    let finish!: (value: CleanupResult) => void;
    api.cleanup.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
    const complete = vi.fn();
    const hook = renderHook(() => useTrajectoryCleanup(complete));
    act(() => {
      void hook.result.current.start(7);
    });
    act(() => hook.result.current.cancel());
    expect(api.cleanup.mock.calls[0][2]?.aborted).toBe(true);
    await act(async () => finish(batch({ done: false, next_cursor: "next" })));
    expect(api.cleanup).toHaveBeenCalledOnce();
    expect(complete).not.toHaveBeenCalled();
    expect(hook.result.current.result).toBeNull();
  });
  it("retains the failed cursor for retry without recounting completed batches", async () => {
    api.cleanup
      .mockResolvedValueOnce(batch({ done: false, next_cursor: "next" }))
      .mockRejectedValueOnce(new Error("busy"))
      .mockResolvedValueOnce(batch());
    const hook = renderHook(() => useTrajectoryCleanup(vi.fn()));
    await act(async () => hook.result.current.start(7));
    expect(hook.result.current.error).toBeTruthy();
    await act(async () => hook.result.current.start(7, true));
    expect(api.cleanup.mock.calls[2][1]).toBe("next");
    expect(hook.result.current.result?.deleted_runs).toBe(2);
  });
});
