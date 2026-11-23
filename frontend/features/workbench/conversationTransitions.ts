// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { t as translate } from "i18next";
import type { AssistantRuntime } from "@assistant-ui/react";

const pendingTransitions = new WeakSet<AssistantRuntime>();

/** Creation workflows always own a separate thread, including empty drafts. */
export async function changeCreationThread(
  runtime: AssistantRuntime,
  applyMode: () => void
): Promise<void> {
  if (pendingTransitions.has(runtime))
    throw new Error(translate("ui.localization.conversationSwitching"));
  pendingTransitions.add(runtime);
  try {
    if (runtime.thread.getState().isRunning)
      throw new Error(translate("ui.localization.waitReplyConversation"));
    if (
      runtime.thread.composer
        .getState()
        .attachments.some((attachment) => attachment.status.type === "running")
    )
      throw new Error(translate("ui.localization.waitUploadConversation"));
    const threads = runtime.threads.getState();
    if (threads.newThreadId) {
      // Nexent initializes locally; reserving the draft prevents assistant-ui
      // from reusing the same empty thread for a different creation mode.
      await runtime.threads.getItemById(threads.newThreadId).initialize();
    }
    await runtime.threads.switchToNewThread();
    applyMode();
  } finally {
    pendingTransitions.delete(runtime);
  }
}

/** Returning from creation uses the same serialized transition boundary. */
export async function returnFromCreation(
  runtime: AssistantRuntime,
  threadId: string,
  restore: () => void
): Promise<void> {
  if (pendingTransitions.has(runtime))
    throw new Error(translate("ui.localization.conversationSwitching"));
  pendingTransitions.add(runtime);
  try {
    if (runtime.thread.getState().isRunning)
      throw new Error(translate("ui.localization.waitReplyConversation"));
    if (
      runtime.thread.composer
        .getState()
        .attachments.some((attachment) => attachment.status.type === "running")
    )
      throw new Error(translate("ui.localization.waitUploadConversation"));
    await runtime.threads.switchToThread(threadId);
    restore();
  } finally {
    pendingTransitions.delete(runtime);
  }
}

/** Change Workbench mounts in place after the current run has settled. */
export async function changeAgentTopology(
  runtime: AssistantRuntime,
  applyTopology: () => Promise<void> | void
): Promise<void> {
  if (pendingTransitions.has(runtime))
    throw new Error(translate("ui.localization.agentSwitching"));
  pendingTransitions.add(runtime);
  try {
    const state = runtime.thread.getState();
    if (state.isRunning)
      throw new Error(translate("ui.localization.waitReplyAgent"));
    const draft = runtime.thread.composer.getState();
    if (
      draft.attachments.some(
        (attachment) => attachment.status.type === "running"
      )
    ) {
      throw new Error(translate("ui.localization.waitUploadAgent"));
    }
    await applyTopology();
  } finally {
    pendingTransitions.delete(runtime);
  }
}
