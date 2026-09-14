"use client";

import { useEffect, useId, type FC } from "react";
import { useAui } from "@assistant-ui/react";
import { useTranslation } from "react-i18next";

import {
  ClarificationCard,
  type ClarificationAnswer,
} from "@/components/interaction/clarification-card";
import { useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import type {
  Nl2AgentCardAction,
  Nl2aRequirementClarificationPayload,
} from "../adapter/remote-chat-model-adapter";

export const RequirementClarificationCard: FC<{
  payload: Nl2aRequirementClarificationPayload;
  disabled?: boolean;
}> = ({ payload, disabled = false }) => {
  const { t } = useTranslation("common");
  const aui = useAui();
  const reactId = useId();
  const cardKey = `requirement_clarification:${reactId}`;
  const { registerCard, submitCard, isCardInteractive } = useNl2AgentFlow();

  useEffect(() => {
    registerCard(cardKey, payload.subtype);
  }, [cardKey, payload.subtype, registerCard]);

  const submit = (answers: ClarificationAnswer[]) => {
    submitCard(cardKey);
    const action: Nl2AgentCardAction = {
      type: "nl2agent_card_action",
      subtype: payload.subtype,
      agent_id: payload.agent_id,
      action: "submit",
      result: {
        answers: answers.map((answer) => ({
          question_id: answer.questionId,
          value: answer.value,
          other_text: answer.otherText,
        })),
      },
    };

    aui.thread().append({
      role: "user",
      content: [
        {
          type: "text",
          text: t(
            "nl2agent.requirementClarification.submittedSummary",
            "Requirements submitted"
          ),
        },
      ],
      metadata: { custom: { nl2agentCardAction: action } },
      startRun: true,
    });
  };

  return (
    <ClarificationCard
      dataSlot="aui-requirement-clarification"
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
