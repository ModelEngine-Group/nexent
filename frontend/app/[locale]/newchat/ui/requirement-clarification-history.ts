// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ClarificationAnswer } from "@/types/clarification";
import type { Nl2aRequirementClarificationPayload } from "../adapter/remote-chat-model-adapter";

interface HistoryMessage {
  id: string;
  role: string;
  metadata?: { custom?: Record<string, unknown> };
}

export interface RequirementSubmission {
  messageId: string;
  answers: ClarificationAnswer[];
}

/** Match only the next user turn, never another card with reused question IDs. */
export function findRequirementSubmission(
  messages: readonly HistoryMessage[],
  sourceMessageId: string | undefined,
  payload: Nl2aRequirementClarificationPayload
): RequirementSubmission | undefined {
  const index = messages.findIndex((message) => message.id === sourceMessageId);
  if (index < 0) return;
  const response = messages[index + 1];
  if (response?.role !== "user") return;
  const action = response.metadata?.custom?.nl2agentCardAction as
    | {
        type?: unknown;
        subtype?: unknown;
        agent_id?: unknown;
        action?: unknown;
        result?: { answers?: unknown };
      }
    | undefined;
  if (
    action?.type !== "nl2agent_card_action" ||
    action.subtype !== "requirement_clarification" ||
    action.action !== "submit" ||
    action.agent_id !== payload.agent_id ||
    !Array.isArray(action.result?.answers) ||
    action.result.answers.length !== payload.questions.length
  )
    return;

  const answers: ClarificationAnswer[] = [];
  const seen = new Set<string>();
  for (const raw of action.result.answers) {
    if (!raw || typeof raw !== "object") return;
    const { question_id: id, value, other_text: otherText } = raw;
    const question = payload.questions.find((item) => item.question_id === id);
    if (
      !question ||
      seen.has(id) ||
      (otherText != null && typeof otherText !== "string")
    )
      return;
    seen.add(id);
    const multiple = question.question_type === "multiple_choice";
    if (
      multiple
        ? !Array.isArray(value) ||
          !value.every((item) => typeof item === "string")
        : typeof value !== "string"
    )
      return;
    const selected: string[] = Array.isArray(value)
      ? value
      : value
        ? [value]
        : [];
    if (
      question.question_type !== "text" &&
      selected.some(
        (id) => !question.options.some((option) => option.option_id === id)
      )
    )
      return;
    if (otherText && (!question.allow_other || !question.other_input_expanded))
      return;
    const hasAnswer = Array.isArray(value)
      ? value.length > 0
      : value.trim().length > 0;
    if (question.required && !hasAnswer && !otherText?.trim()) return;
    answers.push({ questionId: id, value, otherText: otherText ?? null });
  }
  return { messageId: response.id, answers };
}
