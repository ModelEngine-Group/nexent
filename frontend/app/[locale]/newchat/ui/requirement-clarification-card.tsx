"use client";

import { useEffect, useId, useMemo, useState, type FC } from "react";
import { useAui } from "@assistant-ui/react";
import { CircleHelp, Send } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import type {
  Nl2AgentCardAction,
  Nl2aRequirementClarificationPayload,
} from "../adapter/remote-chat-model-adapter";

type AnswerValue = string | string[];

export const RequirementClarificationCard: FC<{
  payload: Nl2aRequirementClarificationPayload;
  disabled?: boolean;
}> = ({ payload, disabled = false }) => {
  const { t } = useTranslation("common");
  const aui = useAui();
  const reactId = useId();
  const cardKey = `requirement_clarification:${reactId}`;
  const { registerCard, submitCard, isCardInteractive } = useNl2AgentFlow();
  const [answers, setAnswers] = useState<Record<string, AnswerValue>>({});
  const [otherAnswers, setOtherAnswers] = useState<Record<string, string>>({});
  const [isSubmitted, setIsSubmitted] = useState(false);

  useEffect(() => {
    registerCard(cardKey, payload.subtype);
  }, [cardKey, payload.subtype, registerCard]);

  const isComplete = useMemo(
    () =>
      payload.questions.every((question) => {
        if (!question.required) return true;
        const answer = answers[question.question_id];
        const hasAnswer = Array.isArray(answer)
          ? answer.length > 0
          : Boolean(answer?.trim());
        return hasAnswer || Boolean(otherAnswers[question.question_id]?.trim());
      }),
    [answers, otherAnswers, payload.questions]
  );
  const isLocked = disabled || isSubmitted || !isCardInteractive(cardKey);

  const toggleMultipleChoice = (questionId: string, optionId: string) => {
    if (isLocked) return;
    setAnswers((current) => {
      const selected = new Set(
        Array.isArray(current[questionId]) ? current[questionId] : []
      );
      if (selected.has(optionId)) selected.delete(optionId);
      else selected.add(optionId);
      return { ...current, [questionId]: Array.from(selected) };
    });
  };

  const submit = () => {
    if (isLocked || !isComplete) return;
    setIsSubmitted(true);
    submitCard(cardKey);

    const action: Nl2AgentCardAction = {
      type: "nl2agent_card_action",
      subtype: payload.subtype,
      agent_id: null,
      action: "submit",
      result: {
        answers: payload.questions.map((question) => ({
          question_id: question.question_id,
          value:
            answers[question.question_id] ??
            (question.question_type === "multiple_choice" ? [] : ""),
          other_text: otherAnswers[question.question_id]?.trim() || null,
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
    <section
      data-slot="aui-requirement-clarification"
      className="my-4 overflow-hidden rounded-lg border bg-card shadow-sm"
    >
      <div className="flex items-center gap-3 border-b bg-muted/30 px-4 py-3">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10">
          <CircleHelp className="size-4 text-primary" />
        </div>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-foreground">
            {t(
              "nl2agent.requirementClarification.title",
              "Clarify requirements"
            )}
          </h3>
          <p className="text-xs text-muted-foreground">
            {t(
              "nl2agent.requirementClarification.description",
              "Provide the details needed to create the agent draft."
            )}
          </p>
        </div>
      </div>

      <div className="space-y-5 p-4">
        {payload.questions.map((question, questionIndex) => {
          const answer = answers[question.question_id];
          return (
            <fieldset key={question.question_id} disabled={isLocked}>
              <legend className="mb-2 text-sm font-medium text-foreground">
                {question.title}
                {question.required ? (
                  <span className="ml-1 text-destructive" aria-hidden>
                    *
                  </span>
                ) : null}
              </legend>

              {question.question_type === "text" ? (
                <textarea
                  value={typeof answer === "string" ? answer : ""}
                  onChange={(event) =>
                    setAnswers((current) => ({
                      ...current,
                      [question.question_id]: event.target.value,
                    }))
                  }
                  rows={3}
                  className="w-full resize-y rounded-md border bg-background px-3 py-2 text-sm outline-none focus:border-primary disabled:cursor-not-allowed"
                />
              ) : (
                <div className="space-y-2">
                  {question.options.map((option, optionIndex) => {
                    const inputId = `${reactId}-${questionIndex}-${optionIndex}`;
                    const checked = Array.isArray(answer)
                      ? answer.includes(option.option_id)
                      : answer === option.option_id;
                    return (
                      <label
                        key={option.option_id}
                        htmlFor={inputId}
                        className="flex items-start gap-2 text-sm text-foreground"
                      >
                        <input
                          id={inputId}
                          type={
                            question.question_type === "single_choice"
                              ? "radio"
                              : "checkbox"
                          }
                          name={
                            question.question_type === "single_choice"
                              ? `${reactId}-${question.question_id}`
                              : undefined
                          }
                          checked={checked}
                          onChange={() => {
                            if (question.question_type === "multiple_choice") {
                              toggleMultipleChoice(
                                question.question_id,
                                option.option_id
                              );
                            } else {
                              setAnswers((current) => ({
                                ...current,
                                [question.question_id]: option.option_id,
                              }));
                            }
                          }}
                          className="mt-0.5 size-4 accent-primary"
                        />
                        <span>{option.label}</span>
                      </label>
                    );
                  })}
                </div>
              )}

              {question.allow_other ? (
                <label className="mt-3 block text-xs text-muted-foreground">
                  <span>
                    {t("nl2agent.requirementClarification.other", "Other")}
                  </span>
                  <input
                    type="text"
                    value={otherAnswers[question.question_id] ?? ""}
                    onChange={(event) =>
                      setOtherAnswers((current) => ({
                        ...current,
                        [question.question_id]: event.target.value,
                      }))
                    }
                    className="mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary disabled:cursor-not-allowed"
                  />
                </label>
              ) : null}
            </fieldset>
          );
        })}
      </div>

      <div className="flex justify-end border-t bg-muted/20 px-4 py-3">
        <Button
          type="button"
          size="sm"
          disabled={isLocked || !isComplete}
          onClick={submit}
        >
          <Send />
          {isSubmitted
            ? t("nl2agent.requirementClarification.submitted", "Submitted")
            : t("nl2agent.requirementClarification.submit", "Submit")}
        </Button>
      </div>
    </section>
  );
};
