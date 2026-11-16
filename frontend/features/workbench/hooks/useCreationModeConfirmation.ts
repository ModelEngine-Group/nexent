// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useLayoutEffect, useRef } from "react";
import type { AssistantRuntime } from "@assistant-ui/react";
import { useTranslation } from "react-i18next";
import type { CreationModeConfirmation } from "@/components/interaction/creation-mode-context";
import { confirmWorkbenchCreationMode } from "../api";
import { formatClarificationQuery } from "@/lib/clarification";
import {
  parseCreationModeForm,
  selectCreationMode,
  type CreationMode,
} from "@/lib/creationMode";
import type { WorkbenchMode } from "../types";

interface Options {
  runtime: AssistantRuntime;
  mode: WorkbenchMode;
  conversationId?: string;
  canCreateAgent: boolean;
  canCreateSkill: boolean;
  changeMode: (mode: CreationMode) => Promise<boolean>;
  onSaved: (conversationId: string) => void;
}

export function useCreationModeConfirmation(
  options: Options
): CreationModeConfirmation {
  const { t, i18n } = useTranslation();
  const latest = useRef(options);
  useLayoutEffect(() => {
    latest.current = options;
  });
  const pending = useRef(new Set<string>());
  const saved = useRef(
    new Map<string, Awaited<ReturnType<typeof confirmWorkbenchCreationMode>>>()
  );
  return {
    canCreateAgent: options.canCreateAgent,
    canCreateSkill: options.canCreateSkill,
    confirm: async ({ threadId, messageId, originalRequest, response }) => {
      const current = latest.current;
      const { runtime, conversationId } = current;
      const mode = selectCreationMode(response.form, response.answers);
      const question = parseCreationModeForm(response.form);
      const thread = runtime.threads.getById(threadId);
      const key = `${threadId}:${messageId}:${JSON.stringify(response)}`;
      const available = () =>
        runtime.threads.getState().mainThreadId === threadId &&
        !thread.getState().isRunning &&
        !thread.getState().isDisabled &&
        thread.getState().messages.at(-1)?.id === messageId;
      if (
        !mode ||
        !question ||
        !available() ||
        pending.current.has(key) ||
        current.mode === "agent_create" ||
        current.mode === "skill_create" ||
        !Number.isInteger(Number(conversationId)) ||
        Number(conversationId) <= 0
      )
        throw new Error(t("chat.clarification.unavailable"));
      if (
        !(mode === "agent_create"
          ? current.canCreateAgent
          : current.canCreateSkill)
      )
        throw new Error(t("workbench.creationConfirmation.noPermission"));
      const query = formatClarificationQuery(
        response.form,
        response.answers,
        i18n.language
      );
      pending.current.add(key);
      try {
        let receipt = saved.current.get(key);
        if (!receipt) {
          receipt = await confirmWorkbenchCreationMode(
            Number(conversationId),
            response
          );
          if (receipt.mode !== mode || !receipt.message_id)
            throw new Error(t("workbench.creationConfirmation.saveFailed"));
          saved.current.set(key, receipt);
          current.onSaved(conversationId!);
        }
        const active = latest.current;
        if (
          !available() ||
          !(mode === "agent_create"
            ? active.canCreateAgent
            : active.canCreateSkill)
        )
          throw new Error(t("chat.clarification.unavailable"));
        if (!(await active.changeMode(mode)))
          throw new Error(t("ui.localization.conversationCreateFailed"));
        thread.append({
          role: "user",
          content: [{ type: "text", text: query }],
          startRun: false,
          metadata: { custom: { clarificationResponse: response } },
        });
        const summary = question.creation_request!.trim();
        runtime.thread.composer.setText(
          originalRequest.trim() && originalRequest.trim() !== summary
            ? `${summary}\n\n${t("workbench.creationConfirmation.originalRequest")}\n${originalRequest}`
            : summary
        );
      } finally {
        pending.current.delete(key);
      }
    },
  };
}
