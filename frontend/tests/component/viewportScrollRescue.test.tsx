// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { ViewportScrollRescue } from "@/app/newchat/assistant-ui/viewport-scroll-rescue";

type AuiThreadState = {
  isRunning: boolean;
  isLoading: boolean;
  messages: unknown[];
};

type ViewportState = {
  isAtBottom: boolean;
  scrollToBottom: (options?: { behavior?: string }) => void;
};

const auiMock = vi.hoisted(() => {
  const scrollToBottom = vi.fn();
  const viewportState: ViewportState = { isAtBottom: false, scrollToBottom };
  const listeners = new Set<(state: ViewportState, prev: ViewportState) => void>();
  const store = {
    getState: () => viewportState,
    subscribe: (listener: (state: ViewportState, prev: ViewportState) => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
  return {
    thread: {
      isRunning: false,
      isLoading: false,
      messages: [] as unknown[],
    } as AuiThreadState,
    viewportState,
    scrollToBottom,
    listeners,
    store,
  };
});

vi.mock("@assistant-ui/react", () => ({
  useAuiState: (selector: (s: { thread: AuiThreadState }) => unknown) =>
    selector({ thread: auiMock.thread }),
  useThreadViewportStore: () => auiMock.store,
}));

const renderRescue = () => {
  const utils = render(<ViewportScrollRescue />);
  return {
    container: utils.container,
    rerender: () => utils.rerender(<ViewportScrollRescue />),
  };
};

/** Simulate a scroll event changing the store's isAtBottom flag. */
const notifyViewportIsAtBottom = (next: boolean) => {
  const prev: ViewportState = { ...auiMock.viewportState };
  auiMock.viewportState.isAtBottom = next;
  for (const listener of auiMock.listeners) {
    listener({ ...auiMock.viewportState }, prev);
  }
};

beforeEach(() => {
  auiMock.thread.isRunning = false;
  auiMock.thread.isLoading = false;
  auiMock.thread.messages = [];
  auiMock.viewportState.isAtBottom = false;
  auiMock.scrollToBottom.mockClear();
});

afterEach(() => {
  cleanup();
});

test("renders nothing and does not scroll on initial mount", () => {
  const { container } = renderRescue();
  expect(container.childElementCount).toBe(0);
  expect(auiMock.scrollToBottom).not.toHaveBeenCalled();
});

test("scrolls to the bottom once when a run starts", () => {
  const { rerender } = renderRescue();

  auiMock.thread.isRunning = true;
  rerender();
  expect(auiMock.scrollToBottom).toHaveBeenCalledTimes(1);
  expect(auiMock.scrollToBottom).toHaveBeenCalledWith({ behavior: "instant" });

  // Re-rendering without new state must not re-trigger the scroll.
  rerender();
  expect(auiMock.scrollToBottom).toHaveBeenCalledTimes(1);

  // The run ending must not scroll either.
  auiMock.thread.isRunning = false;
  rerender();
  expect(auiMock.scrollToBottom).toHaveBeenCalledTimes(1);
});

test("scrolls to the bottom when history finishes loading with messages", () => {
  const { rerender } = renderRescue();

  auiMock.thread.isLoading = true;
  rerender();
  expect(auiMock.scrollToBottom).not.toHaveBeenCalled();

  auiMock.thread.isLoading = false;
  auiMock.thread.messages = [{ id: "history-1" }, { id: "history-2" }];
  rerender();
  expect(auiMock.scrollToBottom).toHaveBeenCalledTimes(1);
});

test("does not scroll when history finishes loading for an empty thread", () => {
  const { rerender } = renderRescue();

  auiMock.thread.isLoading = true;
  rerender();
  auiMock.thread.isLoading = false;
  auiMock.thread.messages = [];
  rerender();
  expect(auiMock.scrollToBottom).not.toHaveBeenCalled();
});

test("follows streamed updates while the run is active", () => {
  const { rerender } = renderRescue();

  auiMock.thread.isRunning = true;
  rerender();
  expect(auiMock.scrollToBottom).toHaveBeenCalledTimes(1);

  auiMock.thread.messages = [{ id: "chunk-1" }];
  rerender();
  expect(auiMock.scrollToBottom).toHaveBeenCalledTimes(2);

  auiMock.thread.messages = [{ id: "chunk-1" }, { id: "chunk-2" }];
  rerender();
  expect(auiMock.scrollToBottom).toHaveBeenCalledTimes(3);
});

test("stops following after the user scrolls away and resumes at the bottom", () => {
  const { rerender } = renderRescue();

  auiMock.thread.isRunning = true;
  rerender();
  expect(auiMock.scrollToBottom).toHaveBeenCalledTimes(1);

  // The run-start scroll landed at the bottom; the user then scrolls away.
  notifyViewportIsAtBottom(true);
  notifyViewportIsAtBottom(false);

  auiMock.thread.messages = [{ id: "chunk-1" }];
  rerender();
  expect(auiMock.scrollToBottom).toHaveBeenCalledTimes(1);

  // Scrolling back to the bottom resumes the follow on the next update.
  notifyViewportIsAtBottom(true);
  auiMock.thread.messages = [{ id: "chunk-1" }, { id: "chunk-2" }];
  rerender();
  expect(auiMock.scrollToBottom).toHaveBeenCalledTimes(2);
});

test("does not follow message updates when no run is active", () => {
  const { rerender } = renderRescue();

  auiMock.thread.messages = [{ id: "edited-1" }];
  rerender();
  auiMock.thread.messages = [{ id: "edited-1" }, { id: "edited-2" }];
  rerender();
  expect(auiMock.scrollToBottom).not.toHaveBeenCalled();
});
