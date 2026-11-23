// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";
import {
  PinnedThreadsProvider,
  usePinnedThreads,
} from "@/app/newchat/assistant-ui/thread-pins";
import { conversationService } from "@/services/conversationService";
import type { WorkbenchPins } from "@/types/conversation";

const snapshot = (ids: number[]): WorkbenchPins => ({
  items: ids.map((id) => ({
    conversation_id: id,
    conversation_title: `History ${id}`,
    create_time: 1,
    update_time: 1,
    pinned_at: "2026-10-14T00:00:00Z",
  })),
});
function Probe() {
  const pins = usePinnedThreads()!;
  return (
    <>
      <output data-testid="pins">{[...pins.pinnedIds].join(",")}</output>
      <output data-testid="order">
        {pins.getPinOrder?.({ id: "local", remoteId: "42" })}
      </output>
      <button
        disabled={!pins.canPin({ id: "local", remoteId: "42" })}
        onClick={() => pins.togglePin({ id: "local", remoteId: "42" })}
      >
        Toggle
      </button>
      <button
        disabled={
          !pins.canPin({ id: "draft", remoteId: "workbench-draft:draft" })
        }
      >
        Draft
      </button>
    </>
  );
}
function setup(scope: string | null = "user-a", error = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = (key: string | null) => (
    <QueryClientProvider client={client}>
      <PinnedThreadsProvider
        serverBacked
        storageKey={key}
        onStorageError={error}
      >
        <Probe />
      </PinnedThreadsProvider>
    </QueryClientProvider>
  );
  return { ...render(view(scope)), client, error, view };
}

async function resumeWindow() {
  vi.useFakeTimers();
  try {
    act(() => window.dispatchEvent(new Event("focus")));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_050);
    });
  } finally {
    vi.useRealTimers();
  }
}

it("loads canonical server order and ignores old local Workbench state", async () => {
  localStorage.setItem("user-a", '["999"]');
  vi.spyOn(conversationService, "getWorkbenchPins").mockResolvedValue(
    snapshot([43, 42])
  );
  const { client } = setup();
  await waitFor(() =>
    expect(screen.getByTestId("pins")).toHaveTextContent("43,42")
  );
  expect(screen.getByTestId("order")).toHaveTextContent("1");
  expect(localStorage.getItem("user-a")).toBe('["999"]');
  expect(screen.getByText("Draft")).toBeDisabled();
  client.clear();
});

it("commits only acknowledged state and prevents duplicate concurrent clicks", async () => {
  vi.spyOn(conversationService, "getWorkbenchPins").mockResolvedValue(
    snapshot([])
  );
  let finish!: (value: WorkbenchPins) => void;
  const save = vi
    .spyOn(conversationService, "setWorkbenchPin")
    .mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
  const { client } = setup();
  await waitFor(() => expect(screen.getByText("Toggle")).toBeEnabled());
  fireEvent.click(screen.getByText("Toggle"));
  fireEvent.click(screen.getByText("Toggle"));
  await waitFor(() => expect(save).toHaveBeenCalledExactlyOnceWith(42, true));
  expect(screen.getByTestId("pins")).toBeEmptyDOMElement();
  await act(async () => finish(snapshot([42])));
  await waitFor(() =>
    expect(screen.getByTestId("pins")).toHaveTextContent("42")
  );
  expect(localStorage.getItem("user-a")).not.toBe('["42"]');
  client.clear();
});

it("unpin uses confirmed server membership and failure preserves state with an error", async () => {
  vi.spyOn(conversationService, "getWorkbenchPins").mockResolvedValue(
    snapshot([42])
  );
  const save = vi
    .spyOn(conversationService, "setWorkbenchPin")
    .mockRejectedValue(new Error("Unavailable"));
  const { client, error } = setup();
  await waitFor(() => expect(screen.getByText("Toggle")).toBeEnabled());
  fireEvent.click(screen.getByText("Toggle"));
  await waitFor(() => expect(error).toHaveBeenCalledTimes(1));
  expect(save).toHaveBeenCalledExactlyOnceWith(42, false);
  expect(screen.getByTestId("pins")).toHaveTextContent("42");
  client.clear();
});

it("read failures disable writes and report the error", async () => {
  vi.spyOn(conversationService, "getWorkbenchPins").mockRejectedValue(
    new Error("Unauthorized")
  );
  const { client, error } = setup();
  await waitFor(() => expect(error).toHaveBeenCalledTimes(1));
  expect(screen.getByText("Toggle")).toBeDisabled();
  client.clear();
});

it("missing identity does not read or write backend pins", () => {
  const get = vi.spyOn(conversationService, "getWorkbenchPins");
  const { client } = setup(null);
  expect(get).not.toHaveBeenCalled();
  expect(screen.getByText("Toggle")).toBeDisabled();
  client.clear();
});

it("identity changes isolate confirmed and late mutation state", async () => {
  vi.spyOn(conversationService, "getWorkbenchPins")
    .mockResolvedValueOnce(snapshot([42]))
    .mockResolvedValueOnce(snapshot([]));
  let finish!: (value: WorkbenchPins) => void;
  vi.spyOn(conversationService, "setWorkbenchPin").mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      })
  );
  const { client, rerender, view } = setup();
  await waitFor(() => expect(screen.getByText("Toggle")).toBeEnabled());
  fireEvent.click(screen.getByText("Toggle"));
  rerender(view("user-b"));
  await waitFor(() => expect(screen.getByText("Toggle")).toBeEnabled());
  await act(async () => finish(snapshot([43])));
  expect(screen.getByTestId("pins")).toBeEmptyDOMElement();
  client.clear();
});

it("focus refresh reads changes from another device", async () => {
  vi.spyOn(conversationService, "getWorkbenchPins")
    .mockResolvedValueOnce(snapshot([42]))
    .mockResolvedValueOnce(snapshot([43, 42]));
  const { client } = setup();
  await waitFor(() =>
    expect(screen.getByTestId("pins")).toHaveTextContent("42")
  );
  await resumeWindow();
  await waitFor(() =>
    expect(screen.getByTestId("pins")).toHaveTextContent("43,42")
  );
  client.clear();
});

it("refreshes on foreground re-entry while ignoring ordinary visible-page interactions", async () => {
  const get = vi
    .spyOn(conversationService, "getWorkbenchPins")
    .mockResolvedValueOnce(snapshot([42]))
    .mockResolvedValue(snapshot([43, 42]));
  const { client, unmount } = setup();
  await waitFor(() =>
    expect(screen.getByTestId("pins")).toHaveTextContent("42")
  );
  fireEvent.pointerDown(document.body);
  fireEvent.focusIn(document.body);
  expect(get).toHaveBeenCalledTimes(1);
  await resumeWindow();
  await waitFor(() =>
    expect(screen.getByTestId("pins")).toHaveTextContent("43,42")
  );
  expect(get).toHaveBeenCalledTimes(2);
  unmount();
  fireEvent.pointerDown(document.body);
  fireEvent.focus(window);
  expect(get).toHaveBeenCalledTimes(2);
  client.clear();
});

it("queues a throttled trailing refresh and cancels it on unmount", async () => {
  const get = vi
    .spyOn(conversationService, "getWorkbenchPins")
    .mockResolvedValue(snapshot([42]));
  const { client, unmount } = setup();
  await waitFor(() =>
    expect(screen.getByTestId("pins")).toHaveTextContent("42")
  );
  vi.useFakeTimers();
  try {
    fireEvent.focus(window);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_050);
    });
    expect(get).toHaveBeenCalledTimes(2);
    get.mockResolvedValue(snapshot([43]));
    fireEvent.focus(window);
    fireEvent.focus(window);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_050);
    });
    expect(get).toHaveBeenCalledTimes(3);
    fireEvent.focus(window);
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_050);
    });
    expect(get).toHaveBeenCalledTimes(3);
  } finally {
    vi.useRealTimers();
    client.clear();
  }
});

it("does not activity-refresh without identity or while hidden", async () => {
  const get = vi
    .spyOn(conversationService, "getWorkbenchPins")
    .mockResolvedValue(snapshot([42]));
  const disabled = setup(null);
  fireEvent.pointerDown(document.body);
  fireEvent.focus(window);
  expect(get).not.toHaveBeenCalled();
  disabled.unmount();
  disabled.client.clear();
  const { client, unmount } = setup();
  await waitFor(() =>
    expect(screen.getByTestId("pins")).toHaveTextContent("42")
  );
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
  fireEvent.pointerDown(document.body);
  fireEvent.focus(window);
  expect(get).toHaveBeenCalledTimes(1);
  unmount();
  client.clear();
});

it("does not start an activity read during an acknowledged pin mutation", async () => {
  const get = vi
    .spyOn(conversationService, "getWorkbenchPins")
    .mockResolvedValue(snapshot([]));
  let finish!: (value: WorkbenchPins) => void;
  vi.spyOn(conversationService, "setWorkbenchPin").mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      })
  );
  const { client, unmount } = setup();
  await waitFor(() => expect(screen.getByText("Toggle")).toBeEnabled());
  fireEvent.click(screen.getByText("Toggle"));
  await resumeWindow();
  expect(get).toHaveBeenCalledTimes(1);
  await act(async () => finish(snapshot([42])));
  await waitFor(() =>
    expect(screen.getByTestId("pins")).toHaveTextContent("42")
  );
  unmount();
  client.clear();
});
