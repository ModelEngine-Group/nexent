// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, fireEvent, render, waitFor } from "@testing-library/react";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { useForegroundRefresh } from "@/hooks/chat/useForegroundRefresh";
import { CONVERSATION_SYNC_FRESHNESS_MS } from "@/const/conversationSync";
import log from "@/lib/logger";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});
const key = ["foreground-fixture"];

it("ignores ordinary clicks and coalesces fresh focus events into one deferred read", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  const fetch = vi.fn().mockResolvedValue({ title: "current" });
  function Probe() {
    useQuery({
      queryKey: key,
      queryFn: fetch,
      staleTime: CONVERSATION_SYNC_FRESHNESS_MS,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
    });
    useForegroundRefresh(key, true);
    return <button>Unrelated interaction</button>;
  }
  const view = render(
    <QueryClientProvider client={client}>
      <Probe />
    </QueryClientProvider>
  );
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  vi.useFakeTimers();
  fireEvent.pointerDown(view.getByRole("button"));
  fireEvent.focusIn(view.getByRole("button"));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(100);
  });
  expect(fetch).toHaveBeenCalledTimes(1);
  act(() => {
    window.dispatchEvent(new Event("focus"));
    document.dispatchEvent(new Event("visibilitychange"));
    window.dispatchEvent(new Event("online"));
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(CONVERSATION_SYNC_FRESHNESS_MS + 5);
  });
  expect(fetch).toHaveBeenCalledTimes(2);
  view.unmount();
  await act(async () => {
    window.dispatchEvent(new Event("focus"));
    await vi.advanceTimersByTimeAsync(6000);
  });
  expect(fetch).toHaveBeenCalledTimes(2);
  client.clear();
});

it("shares an in-flight foreground read and preserves cached data when it fails", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  client.setQueryData(key, { title: "confirmed" });
  let reject!: (reason: Error) => void;
  const fetch = vi.fn(
    () =>
      new Promise((_resolve, fail) => {
        reject = fail;
      })
  );
  const warning = vi.spyOn(log, "warn").mockImplementation(() => {});
  function Probe() {
    useQuery({
      queryKey: key,
      queryFn: fetch,
      staleTime: CONVERSATION_SYNC_FRESHNESS_MS,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
    });
    useForegroundRefresh(key, true);
    return null;
  }
  const view = render(
    <QueryClientProvider client={client}>
      <Probe />
    </QueryClientProvider>
  );
  vi.useFakeTimers();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(6000);
  });
  fireEvent.focus(window);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10);
  });
  expect(fetch).toHaveBeenCalledTimes(1);
  fireEvent.focus(window);
  window.dispatchEvent(new Event("online"));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10);
  });
  expect(fetch).toHaveBeenCalledTimes(1);
  await act(async () => {
    reject(new Error("Offline"));
    await vi.advanceTimersByTimeAsync(10);
  });
  expect(warning).toHaveBeenCalled();
  expect(client.getQueryData(key)).toEqual({ title: "confirmed" });
  expect(client.getQueryState(key)?.fetchStatus).toBe("idle");
  view.unmount();
  client.clear();
});
