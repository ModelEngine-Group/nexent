import type { ThreadMessage, ThreadRuntime } from "@assistant-ui/react";

export function ordinarySendError(error: unknown, language: string): string {
  if (error instanceof Error && error.message === "agent_run_conflict") {
    return language.startsWith("zh")
      ? "上一轮正在结束，请稍后再发送"
      : "The previous run is finishing. Please send again shortly.";
  }
  return error instanceof Error ? error.message : String(error);
}

/** Restore rejected optimistic messages only after the local run has settled. */
export function protectOrdinarySend(
  thread: ThreadRuntime,
  {
    restoreDraft,
    onStarted,
    onRejected,
  }: {
    restoreDraft: boolean;
    onStarted?: () => void;
    onRejected: (error: unknown) => void;
  }
) {
  const before = thread.export();
  const draft = thread.composer.getState();
  let accepted = false;
  let rejected = false;
  let stopWatching: (() => void) | undefined;
  return {
    onRunStarted: () => {
      if (rejected || accepted) return;
      accepted = true;
      onStarted?.();
    },
    onRunRejected: (error: unknown, message?: ThreadMessage) => {
      if (accepted || rejected) return;
      rejected = true;
      const restore = () => {
        if (thread.getState().isRunning) return;
        stopWatching?.();
        thread.import(before);
        if (restoreDraft) {
          const current = thread.composer.getState();
          const original = draft.text;
          thread.composer.setText(
            current.text && current.text !== original
              ? `${original}\n\n${current.text}`
              : original
          );
          for (const attachment of message?.attachments ?? draft.attachments) {
            if (
              !current.attachments.some((item) => item.id === attachment.id)
            ) {
              void thread.composer.addAttachment({
                ...attachment,
                content: attachment.content ?? [],
              });
            }
          }
        }
        onRejected(error);
      };
      stopWatching = thread.subscribe(restore);
      restore();
    },
  };
}
