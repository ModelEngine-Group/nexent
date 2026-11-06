// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

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
import { getConversationResourceLimitMessage } from "@/const/errorMessageI18n";
import { useCreationModeConfirmationContext } from "@/components/interaction/creation-mode-context";
import { parseCreationModeForm, selectCreationMode } from "@/lib/creationMode";

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
  const creationController = useCreationModeConfirmationContext();
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
  const creation = creationController && parseCreationModeForm(form);
  const submit = async (answers: ClarificationAnswer[]) => {
    const thread = runtime.threads.getById(threadId);
    if (
      readOnly ||
      runtime.threads.getState().mainThreadId !== threadId ||
      thread.getState().isDisabled ||
      thread.getState().isRunning ||
      thread.getState().messages.at(-1)?.id !== messageId ||
      !complete ||
      payload?.completed === false ||
      payload?.submitted === true
    ) {
      throw new Error(t("chat.clarification.unavailable"));
    }
    const query = formatClarificationQuery(form, answers, i18n.language);
    if (creation && selectCreationMode(form, answers)) {
      const messages = thread.getState().messages;
      const sourceIndex = messages.findIndex(
        (message) => message.id === messageId
      );
      const source = messages
        .slice(0, sourceIndex)
        .findLast((message) => message.role === "user");
      await creationController!.confirm({
        threadId,
        messageId,
        originalRequest:
          source?.content
            .filter((part) => part.type === "text")
            .map((part) => part.text)
            .join("\n") ?? "",
        response: {
          schema_version: 1,
          form,
          unit_index: payload?.unitIndex ?? null,
          answers,
        },
      });
      return;
    }
    await new Promise<void>((resolve, reject) => {
      const feedback = protectOrdinarySend(thread, {
        restoreDraft: false,
        onStarted: resolve,
        onRejected: (error) =>
          reject(
            new Error(
              ordinarySendError(error, i18n.language, (value) =>
                getConversationResourceLimitMessage(value, t)
              )
            )
          ),
      });
      const config = thread.composer.getState().runConfig;
      thread.append({
        role: "user",
        content: [{ type: "text", text: query }],
        metadata: {
          custom: {
            clarificationResponse: {
              schema_version: 1,
              form,
              unit_index: payload?.unitIndex ?? null,
              answers,
            },
          },
        },
        runConfig: { ...config, custom: { ...config.custom, ...feedback } },
      });
    });
  };
  return (
    <ClarificationCard
      key={`${messageId}:${payload?.unitIndex}:${payload?.submitted === true}`}
      dataSlot="clarification-message"
      title={t(
        creation
          ? "workbench.creationConfirmation.title"
          : "chat.clarification.title"
      )}
      description={t(
        creation
          ? "workbench.creationConfirmation.description"
          : "chat.clarification.description"
      )}
      questions={toCardQuestions(form.questions).map((question) => ({
        ...question,
        options: question.options?.map((option) => ({
          ...option,
          disabled:
            !!creation &&
            (option.id === "agent_create"
              ? !creationController!.canCreateAgent
              : option.id === "skill_create"
                ? !creationController!.canCreateSkill
                : false),
        })),
      }))}
      initialAnswers={payload?.answers}
      submitted={payload?.submitted}
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
            : creation
              ? "workbench.creationConfirmation.hint"
              : "chat.clarification.hint"
      )}
      onSubmit={submit}
    />
  );
}
