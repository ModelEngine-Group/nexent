// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type {
  ClarificationAnswer,
  ClarificationForm,
} from "@/types/clarification";

export type CreationMode = "agent_create" | "skill_create";

/** Validate a model action; natural-language intent is never classified here. */
export function parseCreationModeForm(form: ClarificationForm | null) {
  if (!form || form.questions.length !== 1) return null;
  const question = form.questions[0];
  const ids = question.options.map((option) => option.id);
  if (
    question.id !== "workbench_creation_mode" ||
    question.type !== "single_choice" ||
    !question.required ||
    question.allow_other ||
    !question.creation_request?.trim() ||
    question.creation_request.length > 8000 ||
    !ids.includes("continue_chat") ||
    !ids.some((id) => id === "agent_create" || id === "skill_create") ||
    ids.some(
      (id) => !["agent_create", "skill_create", "continue_chat"].includes(id)
    )
  )
    return null;
  return question;
}

export function selectCreationMode(
  form: ClarificationForm,
  answers: ClarificationAnswer[]
): CreationMode | null {
  const question = parseCreationModeForm(form);
  const answer = answers[0];
  if (
    !question ||
    answers.length !== 1 ||
    answer.questionId !== question.id ||
    typeof answer.value !== "string" ||
    answer.otherText ||
    !question.options.some((option) => option.id === answer.value)
  )
    throw new Error("Invalid creation-mode selection");
  return answer.value === "continue_chat"
    ? null
    : (answer.value as CreationMode);
}
