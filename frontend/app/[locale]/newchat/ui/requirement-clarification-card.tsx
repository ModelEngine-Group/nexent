// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useId, type FC } from "react";
import { useAui } from "@assistant-ui/react";
import { useTranslation } from "react-i18next";

import {
  ClarificationCard,
  type ClarificationAnswer,
} from "@/components/interaction/clarification-card";
import { useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import { formatNl2AgentActionSummary } from "./nl2agent-action-summary";
import { nl2AgentCardRunConfig } from "./nl2agent-card-run-config";
import type {
  Nl2AgentCardAction,
  Nl2aRequirementClarificationPayload,
} from "../adapter/remote-chat-model-adapter";
import type { RequirementSubmission } from "./requirement-clarification-history";

export const RequirementClarificationCard: FC<{
  payload: Nl2aRequirementClarificationPayload;
  disabled?: boolean;
  sourceMessageId?: string;
  submission?: RequirementSubmission;
}> = ({ payload, disabled = false, sourceMessageId, submission }) => {
  const { t } = useTranslation("common");
  const aui = useAui();
  const reactId = useId();
  const cardKey = `requirement_clarification:${payload.agent_id}:${payload.card_id ?? sourceMessageId ?? reactId}`;
  const {
    registerCard,
    submitCard,
    isCardInteractive,
    sessionGeneration,
    draftScope,
  } = useNl2AgentFlow();
  const draftKey = draftScope
    ? JSON.stringify(["creator-card-draft", draftScope, cardKey])
    : undefined;

  useEffect(() => {
    if (!disabled && !submission) registerCard(cardKey, payload.subtype);
  }, [
    cardKey,
    disabled,
    payload.subtype,
    registerCard,
    sessionGeneration,
    submission,
  ]);

  const submit = (answers: ClarificationAnswer[]) => {
    const action: Nl2AgentCardAction = {
      type: "nl2agent_card_action",
      subtype: payload.subtype,
      agent_id: payload.agent_id,
      ...(payload.card_id ? { card_id: payload.card_id } : {}),
      action: "submit",
      result: {
        answers: answers.map((answer) => ({
          question_id: answer.questionId,
          value: answer.value,
          other_text: answer.otherText,
        })),
      },
    };

    const thread = aui.thread();
    const snapshot = thread.export?.();
    return new Promise<void>((resolve, reject) => {
      const base = nl2AgentCardRunConfig(
        thread.composer().getState().runConfig,
        payload.agent_id
      );
      thread.append({
        runConfig: {
          ...base,
          custom: {
            ...base.custom,
            onRunStarted: () => {
              submitCard(cardKey);
              try {
                if (draftKey) sessionStorage.removeItem(draftKey);
              } catch {
                /* Best-effort draft cleanup. */
              }
              resolve();
            },
            onRunRejected: (error: unknown) => {
              // Restore the rejected optimistic turn after assistant-ui leaves running.
              setTimeout(() => {
                if (
                  snapshot &&
                  thread
                    .getState()
                    .messages.some((item) => item.id === sourceMessageId)
                )
                  thread.import(snapshot);
                reject(error);
              }, 0);
            },
          },
        },
        role: "user",
        content: [
          {
            type: "text",
            text: formatNl2AgentActionSummary(payload.subtype, t),
          },
        ],
        metadata: { custom: { nl2agentCardAction: action } },
        startRun: true,
      });
    });
  };

  return (
    <ClarificationCard
      key={JSON.stringify([sourceMessageId ?? reactId, payload, submission])}
      dataSlot="aui-requirement-clarification"
      rowLayout
      title={t(
        "nl2agent.requirementClarification.title",
        "Clarify requirements"
      )}
      description={t(
        "nl2agent.requirementClarification.description",
        "Provide the details needed to configure this Agent."
      )}
      questions={payload.questions.map((question) => ({
        id: question.question_id,
        type: question.question_type,
        title: question.title,
        required: question.required,
        options: question.options.map((option) => ({
          id: option.option_id,
          label: option.label,
        })),
        allowOther: question.allow_other,
        otherInputExpanded: question.other_input_expanded,
      }))}
      disabled={disabled || !isCardInteractive(cardKey)}
      initialAnswers={submission?.answers}
      draftKey={draftKey}
      submitted={submission !== undefined}
      otherLabel={t("nl2agent.requirementClarification.other", "Other")}
      submitLabel={t("nl2agent.requirementClarification.submit", "Submit")}
      submittedLabel={t(
        "nl2agent.requirementClarification.submitted",
        "Submitted"
      )}
      onSubmit={submit}
    />
  );
};
