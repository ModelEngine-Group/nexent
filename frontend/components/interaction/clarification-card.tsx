"use client";

import { useId, useMemo, useState, type ReactNode } from "react";
import { CircleHelp, Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type ClarificationQuestionType =
  | "single_choice"
  | "multiple_choice"
  | "text";

export interface ClarificationOption {
  id: string;
  label: string;
}

export interface ClarificationQuestion {
  id: string;
  type: ClarificationQuestionType;
  title: string;
  required?: boolean;
  options?: ClarificationOption[];
  allowOther?: boolean;
  otherInputExpanded?: boolean;
  placeholder?: string;
}

export interface ClarificationAnswer {
  questionId: string;
  value: string | string[];
  otherText: string | null;
}

const supportsOtherAnswer = (question: ClarificationQuestion) =>
  question.type !== "text" &&
  question.allowOther === true &&
  question.otherInputExpanded === true;

export function InteractionCardShell({
  icon,
  title,
  description,
  children,
  footer,
  className,
  dataSlot,
}: {
  icon?: ReactNode;
  title: string;
  description: string;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
  dataSlot?: string;
}) {
  return (
    <section
      data-slot={dataSlot}
      className={cn(
        "my-4 overflow-hidden rounded-lg border bg-card shadow-sm",
        className
      )}
    >
      <div className="flex items-center gap-3 border-b bg-muted/30 px-4 py-3">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10">
          {icon ?? <CircleHelp className="size-4 text-primary" />}
        </div>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-foreground">{title}</h3>
          <p className="text-xs text-muted-foreground">{description}</p>
        </div>
      </div>
      {children}
      {footer ? (
        <div className="border-t bg-muted/20 px-4 py-3">{footer}</div>
      ) : null}
    </section>
  );
}

export function ClarificationCard({
  title,
  description,
  questions,
  disabled = false,
  submitLabel,
  submittedLabel,
  otherLabel,
  footerHint,
  onSubmit,
  dataSlot,
}: {
  title: string;
  description: string;
  questions: ClarificationQuestion[];
  disabled?: boolean;
  submitLabel: string;
  submittedLabel: string;
  otherLabel: string;
  footerHint?: ReactNode;
  onSubmit: (answers: ClarificationAnswer[]) => void | Promise<void>;
  dataSlot?: string;
}) {
  const reactId = useId();
  const [answers, setAnswers] = useState<Record<string, string | string[]>>({});
  const [otherAnswers, setOtherAnswers] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSubmitted, setIsSubmitted] = useState(false);
  const [error, setError] = useState("");
  const isLocked = disabled || isSubmitting || isSubmitted;

  const isComplete = useMemo(
    () =>
      questions.every((question) => {
        if (!question.required) return true;
        const answer = answers[question.id];
        const hasAnswer = Array.isArray(answer)
          ? answer.length > 0
          : Boolean(answer?.trim());
        return (
          hasAnswer ||
          (supportsOtherAnswer(question) &&
            Boolean(otherAnswers[question.id]?.trim()))
        );
      }),
    [answers, otherAnswers, questions]
  );

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

  const submit = async () => {
    if (isLocked || !isComplete) return;
    setIsSubmitting(true);
    setError("");
    try {
      await onSubmit(
        questions.map((question) => ({
          questionId: question.id,
          value:
            answers[question.id] ??
            (question.type === "multiple_choice" ? [] : ""),
          otherText: supportsOtherAnswer(question)
            ? otherAnswers[question.id]?.trim() || null
            : null,
        }))
      );
      setIsSubmitted(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <InteractionCardShell
      dataSlot={dataSlot}
      title={title}
      description={description}
      footer={
        <div className="space-y-2">
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0 text-xs text-muted-foreground">
              {footerHint}
            </div>
            <Button
              type="button"
              size="sm"
              disabled={isLocked || !isComplete}
              onClick={() => void submit()}
            >
              <Send />
              {isSubmitted ? submittedLabel : submitLabel}
            </Button>
          </div>
        </div>
      }
    >
      <div className="space-y-5 p-4">
        {questions.map((question, questionIndex) => {
          const answer = answers[question.id];
          return (
            <fieldset key={question.id} disabled={isLocked}>
              <legend
                id={`${reactId}-${questionIndex}-title`}
                className="mb-2 whitespace-pre-line text-sm font-medium text-foreground"
              >
                {question.title}
                {question.required ? (
                  <span className="ml-1 text-destructive" aria-hidden>
                    *
                  </span>
                ) : null}
              </legend>

              {question.type === "text" ? (
                <textarea
                  aria-labelledby={`${reactId}-${questionIndex}-title`}
                  aria-required={question.required}
                  value={typeof answer === "string" ? answer : ""}
                  onChange={(event) =>
                    setAnswers((current) => ({
                      ...current,
                      [question.id]: event.target.value,
                    }))
                  }
                  rows={3}
                  maxLength={8000}
                  placeholder={question.placeholder}
                  className="w-full resize-y rounded-md border bg-background px-3 py-2 text-sm outline-none focus:border-primary disabled:cursor-not-allowed"
                />
              ) : (
                <div className="space-y-2">
                  {(question.options ?? []).map((option, optionIndex) => {
                    const inputId = `${reactId}-${questionIndex}-${optionIndex}`;
                    const checked = Array.isArray(answer)
                      ? answer.includes(option.id)
                      : answer === option.id;
                    return (
                      <label
                        key={option.id}
                        htmlFor={inputId}
                        className="flex items-start gap-2 text-sm text-foreground"
                      >
                        <input
                          id={inputId}
                          type={
                            question.type === "single_choice"
                              ? "radio"
                              : "checkbox"
                          }
                          name={
                            question.type === "single_choice"
                              ? `${reactId}-${question.id}`
                              : undefined
                          }
                          checked={checked}
                          onChange={() => {
                            if (question.type === "multiple_choice") {
                              toggleMultipleChoice(question.id, option.id);
                            } else {
                              setAnswers((current) => ({
                                ...current,
                                [question.id]: option.id,
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

              {supportsOtherAnswer(question) ? (
                <label className="mt-3 block text-xs text-muted-foreground">
                  <span>{otherLabel}</span>
                  <input
                    type="text"
                    maxLength={8000}
                    value={otherAnswers[question.id] ?? ""}
                    onChange={(event) =>
                      setOtherAnswers((current) => ({
                        ...current,
                        [question.id]: event.target.value,
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
    </InteractionCardShell>
  );
}
