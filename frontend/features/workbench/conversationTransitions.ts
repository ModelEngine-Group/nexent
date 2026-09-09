import type { AssistantRuntime } from "@assistant-ui/react";

const pendingTransitions = new WeakSet<AssistantRuntime>();

/** Creation workflows always own a separate thread, including empty drafts. */
export async function changeCreationThread(
  runtime: AssistantRuntime,
  applyMode: () => void
): Promise<void> {
  if (pendingTransitions.has(runtime)) throw new Error("会话正在切换，请稍候");
  pendingTransitions.add(runtime);
  try {
    if (runtime.thread.getState().isRunning)
      throw new Error("请等待当前回复完成后再切换会话");
    await runtime.threads.switchToNewThread();
    applyMode();
  } finally {
    pendingTransitions.delete(runtime);
  }
}

/** Preserve the user's unsent input across a topology change. */
export async function changeAgentTopology(
  runtime: AssistantRuntime,
  applyTopology: () => Promise<void> | void
): Promise<void> {
  if (pendingTransitions.has(runtime))
    throw new Error("智能体正在切换，请稍候");
  pendingTransitions.add(runtime);
  try {
    const state = runtime.thread.getState();
    if (state.isRunning) throw new Error("请等待当前回复完成后再切换智能体");
    if (state.messages.length === 0) {
      await applyTopology();
      return;
    }
    const draft = runtime.thread.composer.getState();
    if (
      draft.attachments.some(
        (attachment) => attachment.status.type === "running"
      )
    ) {
      throw new Error("请等待附件上传完成后再切换智能体");
    }
    await runtime.threads.switchToNewThread();
    const destinationComposer = runtime.thread.composer;
    try {
      await applyTopology();
    } finally {
      destinationComposer.setText(draft.text);
      for (const attachment of draft.attachments) {
        if (attachment.status.type === "complete") {
          await destinationComposer.addAttachment({
            ...attachment,
            content: attachment.content ?? [],
          });
        } else if (attachment.file) {
          await destinationComposer.addAttachment(attachment.file);
        }
      }
    }
  } finally {
    pendingTransitions.delete(runtime);
  }
}
