// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { AssistantRuntime } from "@assistant-ui/react";
import { describe, expect, it, vi } from "vitest";

import { applyComposerRunConfig } from "../../app/[locale]/newchat/adapter/composer-run-config";

const makeRuntime = (
  mainThreadId: string | undefined
): { runtime: AssistantRuntime; setRunConfig: ReturnType<typeof vi.fn> } => {
  const setRunConfig = vi.fn();
  const runtime = {
    threads: { getState: () => ({ mainThreadId }) },
    thread: { composer: { setRunConfig } },
  } as unknown as AssistantRuntime;
  return { runtime, setRunConfig };
};

describe("applyComposerRunConfig", () => {
  it("applies the config when the runtime main thread matches the active thread", () => {
    const { runtime, setRunConfig } = makeRuntime("thread-2");

    const applied = applyComposerRunConfig(runtime, "thread-2", {
      threadId: "77",
    });

    expect(applied).toBe(true);
    expect(setRunConfig).toHaveBeenCalledTimes(1);
    expect(setRunConfig).toHaveBeenCalledWith({ custom: { threadId: "77" } });
  });

  it("skips the config while the runtime has already switched to a new thread", () => {
    // The "new conversation" flow: the runtime switched to thread-2, but the
    // page state still reports thread-1 and its conversation binding.
    // Writing that config would merge thread-2's first message into
    // thread-1's conversation.
    const { runtime, setRunConfig } = makeRuntime("thread-2");

    const applied = applyComposerRunConfig(runtime, "thread-1", {
      threadId: "77",
    });

    expect(applied).toBe(false);
    expect(setRunConfig).not.toHaveBeenCalled();
  });

  it("skips the config while the runtime still runs the previous thread after the state moved on", () => {
    const { runtime, setRunConfig } = makeRuntime("thread-1");

    const applied = applyComposerRunConfig(runtime, "thread-2", {
      threadId: "77",
    });

    expect(applied).toBe(false);
    expect(setRunConfig).not.toHaveBeenCalled();
  });

  it("skips the config when there is no active thread", () => {
    const { runtime, setRunConfig } = makeRuntime(undefined);

    const applied = applyComposerRunConfig(runtime, undefined, {
      threadId: "77",
    });

    expect(applied).toBe(false);
    expect(setRunConfig).not.toHaveBeenCalled();
  });
});
