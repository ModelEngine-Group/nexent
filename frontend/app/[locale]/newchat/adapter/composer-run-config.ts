// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { AssistantRuntime } from "@assistant-ui/react";

/**
 * Apply the composer run configuration for the active thread.
 *
 * The runtime can switch its main thread (e.g. "new conversation") before the
 * page's `activeThreadId` state catches up. Writing a configuration derived
 * from the stale thread at that moment would land the previous conversation's
 * binding on the new thread: the new thread's first message would then be
 * appended to the previous conversation instead of creating a new one, and
 * the new conversation would never appear in the sidebar.
 *
 * Skip until the page state and the runtime main thread agree; the page
 * effect re-runs once the state catches up and applies the configuration
 * then.
 *
 * Returns whether the configuration was applied.
 */
export function applyComposerRunConfig(
  runtime: AssistantRuntime,
  activeThreadId: string | undefined,
  custom: Record<string, unknown>
): boolean {
  if (!activeThreadId) return false;
  if (runtime.threads.getState().mainThreadId !== activeThreadId) {
    return false;
  }
  runtime.thread.composer.setRunConfig({ custom });
  return true;
}
