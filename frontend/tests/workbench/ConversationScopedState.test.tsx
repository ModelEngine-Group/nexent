// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, renderHook } from "@testing-library/react";
import { expect, it } from "vitest";
import { useConversationScopedState } from "@/features/workbench/hooks/useConversationScopedState";

it("retains edits within a session and resets from its target snapshot on switch", () => {
  const { result, rerender } = renderHook(
    ({ key, initial }) => useConversationScopedState(key, initial),
    { initialProps: { key: "a", initial: { ticket: "saved-a" } } }
  );
  const updateA = result.current[1];
  act(() => updateA({ ticket: "edited-a" }));
  rerender({ key: "a", initial: { ticket: "refetched-a" } });
  expect(result.current[0]).toEqual({ ticket: "edited-a" });
  expect(result.current[1]).toBe(updateA);
  rerender({ key: "b", initial: { ticket: "saved-b" } });
  expect(result.current[0]).toEqual({ ticket: "saved-b" });
  act(() => updateA({ ticket: "late-a" }));
  expect(result.current[0]).toEqual({ ticket: "saved-b" });
});

it("rejects stale functional updates and supports current metadata acknowledgements", () => {
  const { result, rerender } = renderHook(
    ({ key }) => useConversationScopedState(key, 0),
    { initialProps: { key: "a" } }
  );
  const acknowledgeA = result.current[1];
  act(() => acknowledgeA((version) => version + 1));
  expect(result.current[0]).toBe(1);
  rerender({ key: "b" });
  act(() => acknowledgeA((version) => version + 10));
  expect(result.current[0]).toBe(0);
  act(() => result.current[1]((version) => version + 1));
  expect(result.current[0]).toBe(1);
  rerender({ key: "a" });
  expect(result.current[0]).toBe(0);
});
