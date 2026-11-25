// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { ArrowRight, CircleHelp, ListChecks, Send } from "lucide-react";
import { useEffect, useId, useMemo, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type {
  ClarificationAnswer,
  ClarificationQuestion,
} from "@/types/clarification";
export type {
  ClarificationAnswer,
  ClarificationOption,
  ClarificationQuestion,
  ClarificationQuestionType,
} from "@/types/clarification";

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
  rowLayout = false,
}: {
  icon?: ReactNode;
  title: string;
  description: string;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
  dataSlot?: string;
  rowLayout?: boolean;
}) {
  return (
    <section
      data-slot={dataSlot}
      className={cn(
        "my-4 overflow-hidden rounded-lg border bg-card shadow-sm",
        rowLayout && "rounded-2xl border-border text-sm text-foreground",
        className
      )}
    >
      <div
        className={cn(
          "flex gap-3 border-b px-4",
          rowLayout
            ? "items-start bg-muted/25 py-3.5"
            : "items-center bg-muted/30 py-3"
        )}
      >
        <div
          className={cn(
            "flex shrink-0 items-center justify-center",
            rowLayout
              ? "size-8 rounded-lg bg-brand-soft text-primary"
              : "size-9 rounded-md bg-primary/10"
          )}
        >
          {icon ?? <CircleHelp className="size-4 text-primary" />}
        </div>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-foreground">{title}</h3>
          <p
            className={cn(
              "text-xs text-muted-foreground",
              rowLayout && "mt-0.5"
            )}
          >
            {description}
          </p>
        </div>
      </div>
      {children}
      {footer ? (
        <div className={cn("border-t px-4 py-3", !rowLayout && "bg-muted/20")}>
          {footer}
        </div>
      ) : null}
    </section>
  );
}

export function ClarificationCard({
  title,
  description,
  questions,
  disabled = false,
  readOnly = false,
  submitDisabled = false,
  submitLabel,
  submittedLabel,
  otherLabel,
  footerHint,
  onSubmit,
  dataSlot,
  initialAnswers = [],
  submitted = false,
  rowLayout = false,
  draftKey,
}: {
  title: string;
  description: string;
  questions: ClarificationQuestion[];
  disabled?: boolean;
  readOnly?: boolean;
  submitDisabled?: boolean;
  submitLabel: string;
  submittedLabel: string;
  otherLabel: string;
  footerHint?: ReactNode;
  onSubmit: (answers: ClarificationAnswer[]) => void | Promise<void>;
  dataSlot?: string;
  initialAnswers?: ClarificationAnswer[];
  submitted?: boolean;
  rowLayout?: boolean;
  draftKey?: string;
}) {
  const reactId = useId();
  const [draft] = useState(() => {
    if (!draftKey || submitted) return null;
    try {
      const value = JSON.parse(sessionStorage.getItem(draftKey) ?? "null");
      if (!Array.isArray(value)) return null;
      return value.filter(
        (item): item is ClarificationAnswer =>
          item &&
          questions.some((question) => question.id === item.questionId) &&
          (typeof item.value === "string" ||
            (Array.isArray(item.value) &&
              item.value.every((v: unknown) => typeof v === "string"))) &&
          (item.otherText == null || typeof item.otherText === "string")
      );
    } catch {
      return null;
    }
  });
  const [answers, setAnswers] = useState<Record<string, string | string[]>>(
    () =>
      Object.fromEntries(
        (draft ?? initialAnswers).map((answer) => [
          answer.questionId,
          answer.value,
        ])
      )
  );
  const [otherAnswers, setOtherAnswers] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      (draft ?? initialAnswers).map((answer) => [
        answer.questionId,
        answer.otherText ?? "",
      ])
    )
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSubmitted, setIsSubmitted] = useState(submitted);
  const [error, setError] = useState("");
  const isLocked = disabled || readOnly || isSubmitting || isSubmitted;
  useEffect(() => {
    if (!draftKey) return;
    try {
      if (isSubmitted) return;
      else
        sessionStorage.setItem(
          draftKey,
          JSON.stringify(
            questions.map((question) => ({
              questionId: question.id,
              value:
                answers[question.id] ??
                (question.type === "multiple_choice" ? [] : ""),
              otherText: otherAnswers[question.id] ?? null,
            }))
          )
        );
    } catch {
      /* Storage availability must not disable the form. */
    }
  }, [draftKey, isSubmitted, answers, otherAnswers, questions]);

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
    if (isLocked || submitDisabled || !isComplete) return;
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
      icon={
        rowLayout ? (
          <ListChecks className="size-4 text-primary" aria-hidden="true" />
        ) : undefined
      }
      rowLayout={rowLayout}
      footer={
        <div className="space-y-2">
          {error ? (
            <p
              role="alert"
              className={cn(
                "text-destructive",
                rowLayout ? "text-xs" : "text-sm"
              )}
            >
              {error}
            </p>
          ) : null}
          <div
            className={cn(
              "flex flex-wrap items-center justify-end",
              rowLayout ? "gap-2" : "gap-4"
            )}
          >
            {footerHint ? (
              <div className="min-w-0 flex-1 basis-40 text-xs text-muted-foreground">
                {footerHint}
              </div>
            ) : null}
            <Button
              type="button"
              size="sm"
              className={
                rowLayout
                  ? "h-7 gap-1.5 px-2.5 py-0 text-xs [&_svg]:size-3.5"
                  : undefined
              }
              disabled={isLocked || submitDisabled || !isComplete}
              onClick={() => void submit()}
            >
              {!rowLayout ? <Send /> : null}
              {isSubmitted ? submittedLabel : submitLabel}
              {rowLayout ? <ArrowRight aria-hidden="true" /> : null}
            </Button>
          </div>
        </div>
      }
    >
      <div className={rowLayout ? "divide-y divide-border" : "space-y-5 p-4"}>
        {questions.map((question, questionIndex) => {
          const answer = answers[question.id];
          return (
            <div
              key={question.id}
              className={
                rowLayout ? "flex items-start gap-3 px-4 py-3" : undefined
              }
            >
              {rowLayout ? (
                <span
                  aria-hidden="true"
                  className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-brand-soft text-xs tabular-nums text-primary"
                >
                  {questionIndex + 1}
                </span>
              ) : null}
              <fieldset
                className={rowLayout ? "min-w-0 flex-1" : undefined}
                disabled={isLocked}
              >
                <legend
                  id={`${reactId}-${questionIndex}-title`}
                  className={cn(
                    "mb-2 whitespace-pre-line break-words text-foreground",
                    rowLayout ? "text-xs font-semibold" : "text-sm font-medium"
                  )}
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
                    rows={rowLayout ? 2 : 3}
                    maxLength={8000}
                    placeholder={question.placeholder}
                    className={cn(
                      "w-full resize-y rounded-md border bg-background px-3 py-2 outline-none focus:border-primary disabled:cursor-not-allowed",
                      rowLayout ? "text-xs" : "text-sm"
                    )}
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
                          className={cn(
                            "flex items-start gap-2 text-foreground",
                            rowLayout ? "text-xs" : "text-sm"
                          )}
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
                            disabled={isLocked || option.disabled}
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
                      className={cn(
                        "mt-1 w-full rounded-md border bg-background px-3 py-2 text-foreground outline-none focus:border-primary disabled:cursor-not-allowed",
                        rowLayout ? "text-xs" : "text-sm"
                      )}
                    />
                  </label>
                ) : null}
              </fieldset>
            </div>
          );
        })}
      </div>
    </InteractionCardShell>
  );
}
