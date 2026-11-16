// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { t as translate } from "i18next";
import type { AssistantRuntime } from "@assistant-ui/react";

const pendingTransitions = new WeakSet<AssistantRuntime>();

async function switchToFreshThread(runtime: AssistantRuntime): Promise<void> {
  const threads = runtime.threads.getState();
  if (threads.newThreadId) {
    // Reserve an unsent draft so the next action cannot reuse its composer.
    await runtime.threads.getItemById(threads.newThreadId).initialize();
  }
  await runtime.threads.switchToNewThread();
}

/** A new conversation stays independent of drafts, including active runs. */
export async function startWorkbenchConversation(
  runtime: AssistantRuntime,
  prepare: () => void
): Promise<void> {
  if (pendingTransitions.has(runtime))
    throw new Error(translate("ui.localization.conversationSwitching"));
  pendingTransitions.add(runtime);
  try {
    await switchToFreshThread(runtime);
    prepare();
  } finally {
    pendingTransitions.delete(runtime);
  }
}

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
    await switchToFreshThread(runtime);
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
