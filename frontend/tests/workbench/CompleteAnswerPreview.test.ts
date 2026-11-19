// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it } from "vitest";
import { createFinalAnswerProjection } from "@/lib/finalAnswerProjection";

interface AnswerPart {
  type: string;
  text: string;
  isFinalAnswer?: boolean;
  isAnswerPreview?: boolean;
}

const preview = (content: string, step_id = "s") => ({
  type: "model_output_thinking",
  content,
  step_id,
  answer_phase: "delta" as const,
  answer_preview: true,
});

it("confirms the same preview part without appending a duplicate body", () => {
  const parts: AnswerPart[] = [];
  const projection = createFinalAnswerProjection(parts);
  projection.apply(preview("Long "));
  const slot = parts[0];
  projection.apply(preview("answer"));
  expect(slot).toMatchObject({ text: "Long answer", isFinalAnswer: false });
  projection.apply({
    type: "final_answer",
    content: "Long answer",
    answer_phase: "complete",
    step_id: "s",
  });
  expect(parts).toEqual([slot]);
  expect(slot).toMatchObject({ text: "Long answer", isFinalAnswer: true });
  expect(slot.isAnswerPreview).toBe(false);
});

it("rolls back rejected previews and preserves sibling answers", () => {
  const parts: AnswerPart[] = [];
  const projection = createFinalAnswerProjection(parts);
  projection.apply({
    type: "final_answer",
    content: "Previous",
    answer_phase: "complete",
    step_id: "old",
  });
  projection.apply({
    type: "final_answer",
    content: "Child",
    invocation_id: "child",
  });
  projection.control({
    type: "model_attempt_control",
    content: "",
    phase: "begin",
    attempt_id: "bad",
  });
  projection.apply(preview("Rejected", "new"));
  expect(parts[0]).toMatchObject({ text: "Rejected", isFinalAnswer: false });
  projection.control({
    type: "model_attempt_control",
    content: "",
    phase: "rollback",
    attempt_id: "bad",
  });
  expect(parts.map((part) => part.text)).toEqual(["Previous", "Child"]);
  expect(parts[0].isFinalAnswer).toBe(true);
});

it("removes a rolled-back first preview and keeps an errored preview unconfirmed", () => {
  const parts: AnswerPart[] = [];
  const projection = createFinalAnswerProjection(parts);
  projection.control({
    type: "model_attempt_control",
    content: "",
    phase: "begin",
    attempt_id: "bad",
  });
  projection.apply(preview("Rejected"));
  projection.control({
    type: "model_attempt_control",
    content: "",
    phase: "rollback",
    attempt_id: "bad",
  });
  expect(parts).toEqual([]);
  projection.apply(preview("Partial"));
  expect(parts[0]).toMatchObject({ text: "Partial", isFinalAnswer: false });
});
