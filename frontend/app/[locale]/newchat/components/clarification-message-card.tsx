"use client";

import { useAui, useAuiState } from "@assistant-ui/react";
import { useTranslation } from "react-i18next";
import { ClarificationCard } from "@/components/interaction/clarification-card";
import {
  formatClarificationQuery,
  parseClarification,
  toCardQuestions,
} from "@/lib/clarification";
import type {
  ClarificationAnswer,
  ClarificationMessageData,
} from "@/types/clarification";
import { ordinarySendError, protectOrdinarySend } from "../utils/ordinary-send";

export function ClarificationMessageCard({
  data,
  readOnly = false,
}: {
  data: unknown;
  readOnly?: boolean;
}) {
  const aui = useAui();
  const runtime = aui.threads().__internal_getAssistantRuntime?.();
  const { t, i18n } = useTranslation();
  const messageId = useAuiState((state) => state.message.id);
  const threadId = useAuiState((state) => state.threads.mainThreadId);
  const isLast = useAuiState(
    (state) => state.thread.messages.at(-1)?.id === state.message.id
  );
  const isRunning = useAuiState((state) => state.thread.isRunning);
  const disabled = useAuiState((state) => state.thread.isDisabled);
  const complete = useAuiState(
    (state) => state.message.status?.type === "complete"
  );
  const payload = data as ClarificationMessageData | undefined;
  const form = parseClarification(payload?.form);
  if (!form || !runtime) return null;
  const submit = async (answers: ClarificationAnswer[]) => {
    const thread = runtime.threads.getById(threadId);
    if (
      readOnly ||
      runtime.threads.getState().mainThreadId !== threadId ||
      thread.getState().isDisabled ||
      thread.getState().isRunning ||
      thread.getState().messages.at(-1)?.id !== messageId ||
      !complete ||
      payload?.completed === false
    ) {
      throw new Error(t("chat.clarification.unavailable"));
    }
    const query = formatClarificationQuery(form, answers, i18n.language);
    await new Promise<void>((resolve, reject) => {
      const feedback = protectOrdinarySend(thread, {
        restoreDraft: false,
        onStarted: resolve,
        onRejected: (error) =>
          reject(new Error(ordinarySendError(error, i18n.language))),
      });
      const config = thread.composer.getState().runConfig;
      thread.append({
        role: "user",
        content: [{ type: "text", text: query }],
        runConfig: { ...config, custom: { ...config.custom, ...feedback } },
      });
    });
  };
  return (
    <ClarificationCard
      dataSlot="clarification-message"
      title={t("chat.clarification.title")}
      description={t("chat.clarification.description")}
      questions={toCardQuestions(form.questions)}
      readOnly={
        readOnly ||
        disabled ||
        !isLast ||
        payload?.completed === false ||
        (!isRunning && !complete)
      }
      submitDisabled={isRunning || !complete}
      otherLabel={t("chat.clarification.other")}
      submitLabel={t("chat.clarification.submit")}
      submittedLabel={t("chat.clarification.submitted")}
      footerHint={t(
        !isLast
          ? "chat.clarification.history"
          : isRunning
            ? "chat.clarification.saving"
            : "chat.clarification.hint"
      )}
      onSubmit={submit}
    />
  );
}
