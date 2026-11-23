// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { AssistantRuntime } from "@assistant-ui/react";
import { useWorkbenchComposerDraft } from "@/features/workbench/hooks/useWorkbenchComposerDraft";
import { readWorkbenchDraft, workbenchDraftKey } from "@/lib/workbenchDrafts";

beforeEach(() => sessionStorage.clear());
function fixture() {
  let text = "",
    running = false;
  const listeners = new Set<() => void>();
  const composer = {
    getState: () => ({ text }),
    setText: (value: string) => {
      text = value;
      listeners.forEach((fn) => fn());
    },
    subscribe: (fn: () => void) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
  return {
    composer,
    running: (value: boolean) => {
      running = value;
    },
    runtime: {
      thread: { composer, getState: () => ({ isRunning: running }) },
    } as unknown as AssistantRuntime,
  };
}
const defaults = {
  identity: "tenant:user",
  threadId: "local1",
  enabled: true,
  isRunning: false,
  mode: "execution" as const,
  setMode: vi.fn(),
};

it("restores a new unsent execution draft after remount with a new local runtime id", async () => {
  const a = fixture();
  const first = renderHook(() =>
    useWorkbenchComposerDraft({ ...defaults, runtime: a.runtime })
  );
  await act(async () => a.composer.setText("unsent text"));
  first.unmount();
  const b = fixture();
  const second = renderHook(() =>
    useWorkbenchComposerDraft({
      ...defaults,
      threadId: "local2",
      runtime: b.runtime,
    })
  );
  expect(b.composer.getState().text).toBe("unsent text");
  second.unmount();
});

it("retains rejected submissions and clears only the admitted message", async () => {
  const f = fixture();
  const hook = renderHook((props) => useWorkbenchComposerDraft(props), {
    initialProps: { ...defaults, runtime: f.runtime },
  });
  await act(async () => f.composer.setText("submitted"));
  f.running(true);
  hook.rerender({ ...defaults, runtime: f.runtime, isRunning: true });
  await act(async () => f.composer.setText(""));
  f.running(false);
  hook.rerender({ ...defaults, runtime: f.runtime, isRunning: false });
  expect(f.composer.getState().text).toBe("submitted");
  f.running(true);
  hook.rerender({ ...defaults, runtime: f.runtime, isRunning: true });
  await act(async () => f.composer.setText(""));
  act(() => hook.result.current.acknowledge("submitted"));
  expect(
    readWorkbenchDraft(workbenchDraftKey(defaults.identity))
  ).toBeUndefined();
  hook.unmount();
});

it("does not let a late acknowledgement clear newly typed follow-up input", async () => {
  const f = fixture();
  const hook = renderHook(() =>
    useWorkbenchComposerDraft({ ...defaults, runtime: f.runtime })
  );
  await act(async () => f.composer.setText("follow up"));
  act(() => hook.result.current.acknowledge("old question"));
  expect(readWorkbenchDraft(workbenchDraftKey(defaults.identity))?.text).toBe(
    "follow up"
  );
  hook.unmount();
});

it("isolates new threads, users and persisted conversation drafts", async () => {
  const f = fixture();
  const hook = renderHook((props) => useWorkbenchComposerDraft(props), {
    initialProps: { ...defaults, runtime: f.runtime },
  });
  await act(async () => f.composer.setText("old draft"));
  await act(async () => f.composer.setText(""));
  hook.rerender({ ...defaults, runtime: f.runtime, threadId: "new-thread" });
  expect(f.composer.getState().text).toBe("");
  expect(workbenchDraftKey("other", "12")).not.toBe(
    workbenchDraftKey(defaults.identity, "12")
  );
  hook.unmount();
});

it("does not expose the previous account draft when identity changes in place", async () => {
  const f = fixture();
  const hook = renderHook((props) => useWorkbenchComposerDraft(props), {
    initialProps: { ...defaults, runtime: f.runtime },
  });
  await act(async () => f.composer.setText("owner-only"));
  hook.rerender({
    ...defaults,
    runtime: f.runtime,
    identity: "different:owner",
  });
  expect(f.composer.getState().text).toBe("");
  expect(readWorkbenchDraft(workbenchDraftKey(defaults.identity))?.text).toBe(
    "owner-only"
  );
  hook.unmount();
});

it("migrates a new-thread draft to its server conversation without refilling an admitted message", async () => {
  const f = fixture();
  const props = {
    ...defaults,
    runtime: f.runtime,
    conversationId: undefined as string | undefined,
  };
  const hook = renderHook((p) => useWorkbenchComposerDraft(p), {
    initialProps: props,
  });
  await act(async () => f.composer.setText("admitted"));
  const acknowledge = hook.result.current.acknowledge;
  f.running(true);
  hook.rerender({ ...props, isRunning: true });
  await act(async () => f.composer.setText(""));
  hook.rerender({ ...props, isRunning: true, conversationId: "99" });
  act(() => acknowledge("admitted"));
  f.running(false);
  hook.rerender({ ...props, conversationId: "99" });
  expect(f.composer.getState().text).toBe("");
  expect(
    readWorkbenchDraft(workbenchDraftKey(defaults.identity, "99"))
  ).toBeUndefined();
  hook.unmount();
});
