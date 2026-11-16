// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import {
  useSourcesPanelState,
  type SourcesPanelSelection,
} from "@/app/newchat/ui/sources-panel-context";

const first: SourcesPanelSelection = {
  messageId: "answer-1",
  groupId: "retrieval",
  sources: [],
  images: [],
};

it("notifies on explicit opens and different groups, but never on close", () => {
  const onOpen = vi.fn();
  const { result, rerender } = renderHook(() => useSourcesPanelState(onOpen));
  expect(result.current.isOpen).toBe(false);
  act(() => result.current.toggle(first));
  expect(onOpen).toHaveBeenCalledTimes(1);
  expect(result.current.selection).toBe(first);
  rerender();
  expect(onOpen).toHaveBeenCalledTimes(1);
  act(() => result.current.toggle(first));
  expect(result.current.isOpen).toBe(false);
  expect(onOpen).toHaveBeenCalledTimes(1);
  act(() => result.current.open(first));
  act(() => result.current.open(first));
  const other = { ...first, messageId: "answer-2" };
  act(() => result.current.toggle(other));
  expect(result.current.selection).toBe(other);
  expect(onOpen).toHaveBeenCalledTimes(4);
  act(() => result.current.close());
  expect(result.current.isOpen).toBe(false);
  expect(onOpen).toHaveBeenCalledTimes(4);
});

it("preserves standalone conversation selection without an open callback", () => {
  const { result } = renderHook(() => useSourcesPanelState());
  act(() => result.current.open(first));
  expect(result.current.selection).toBe(first);
  act(() => result.current.close());
  expect(result.current.selection).toBeNull();
});

it("dismisses selection on a close epoch change and allows a fresh open", () => {
  const onOpen = vi.fn();
  const { result, rerender } = renderHook(
    ({ epoch }) => useSourcesPanelState(onOpen, epoch),
    { initialProps: { epoch: 0 } }
  );
  act(() => result.current.open(first));
  rerender({ epoch: 0 });
  expect(result.current.selection).toBe(first);
  rerender({ epoch: 1 });
  expect(result.current.selection).toBeNull();
  expect(result.current.isOpen).toBe(false);
  expect(onOpen).toHaveBeenCalledTimes(1);
  rerender({ epoch: 1 });
  expect(result.current.isOpen).toBe(false);
  act(() => result.current.toggle(first));
  expect(result.current.selection).toBe(first);
  expect(onOpen).toHaveBeenCalledTimes(2);
});
