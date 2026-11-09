// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it } from "vitest";
import { parseCreationModeForm, selectCreationMode } from "@/lib/creationMode";
import { parseClarification } from "@/lib/clarification";

const question = {
  id: "workbench_creation_mode",
  type: "single_choice",
  title: "要进入创建模式吗？",
  required: true,
  allow_other: false,
  creation_request: "整理论文，保留原文出处，输出中文摘要。",
  options: [
    { id: "agent_create", label: "创建智能体" },
    { id: "continue_chat", label: "继续对话" },
  ],
};
const raw = { schema_version: 1, questions: [question] };

it("accepts only the AI structured action and preserves its multi-turn request", () => {
  const form = parseClarification(raw)!;
  expect(parseCreationModeForm(form)?.creation_request).toBe(
    question.creation_request
  );
  expect(
    selectCreationMode(form, [
      { questionId: question.id, value: "agent_create", otherText: null },
    ])
  ).toBe("agent_create");
  expect(
    selectCreationMode(form, [
      { questionId: question.id, value: "continue_chat", otherText: null },
    ])
  ).toBeNull();
});

it.each([
  { ...question, id: "ordinary_question" },
  { ...question, creation_request: "" },
  { ...question, type: "multiple_choice" },
  { ...question, allow_other: true },
  {
    ...question,
    options: [{ id: "delete_agent", label: "Other" }, question.options[1]],
  },
])(
  "rejects unsupported action metadata without classifying input text",
  (changed) => {
    expect(
      parseCreationModeForm(
        parseClarification({ ...raw, questions: [changed] })
      )
    ).toBeNull();
  }
);

it("never accepts a forged or multiple creation selection", () => {
  const form = parseClarification(raw)!;
  expect(() =>
    selectCreationMode(form, [
      { questionId: question.id, value: "skill_create", otherText: null },
    ])
  ).toThrow();
  expect(() =>
    selectCreationMode(form, [
      { questionId: question.id, value: ["agent_create"], otherText: null },
    ])
  ).toThrow();
});
