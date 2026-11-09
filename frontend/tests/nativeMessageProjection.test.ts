// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import assert from "node:assert/strict";
import test from "node:test";
// @ts-expect-error -- Node's built-in TypeScript runner needs the extension.
import { createFinalAnswerProjection } from "../lib/finalAnswerProjection.ts";

const event = (step_id: string, content: string, extra = {}) => ({
  type: "model_output",
  step_id,
  content,
  ...extra,
});

test("native public text keeps its position before tools and later final output", () => {
  const parts: any[] = [];
  const projection = createFinalAnswerProjection(parts);
  projection.message(event("1", "Checking "));
  projection.message(event("1", "files."));
  parts.push({ type: "tool-call", toolName: "list_directory" });
  projection.message(event("2", "The result is ready."));
  projection.apply(
    event("2", "", {
      type: "final_answer",
      reclassify_step: true,
      answer_phase: "complete",
    })
  );
  assert.equal(parts.length, 3);
  assert.equal(parts[0].text, "Checking files.");
  assert.equal(parts[0].isIntermediateMessage, true);
  assert.equal(parts[1].type, "tool-call");
  assert.equal(parts[2].text, "The result is ready.");
  assert.equal(parts[2].isFinalAnswer, true);
  assert.equal(parts[2].isIntermediateMessage, undefined);
});

test("native retry rollback removes failed text and retains committed earlier steps", () => {
  const parts: any[] = [];
  const projection = createFinalAnswerProjection(parts);
  projection.message(event("1", "Committed progress"));
  projection.control(event("2", "", { attempt_id: "a", phase: "begin" }));
  projection.message(event("2", "Truncated candidate"));
  projection.control(event("2", "", { attempt_id: "a", phase: "rollback" }));
  assert.deepEqual(
    parts.map((part) => part.text),
    ["Committed progress"]
  );
  projection.message(event("2", "Successful retry"));
  projection.apply(
    event("2", "", { reclassify_step: true, answer_phase: "complete" })
  );
  assert.deepEqual(
    parts.map((part) => part.text),
    ["Committed progress", "Successful retry"]
  );
});

test("native child messages and rollback keep parent scope independent", () => {
  const parts: any[] = [];
  const projection = createFinalAnswerProjection(parts);
  projection.message(event("1", "Parent"));
  const child = { invocation_id: "child" };
  projection.control(
    event("1", "", { ...child, attempt_id: "child-a", phase: "begin" })
  );
  projection.message(event("1", "Child partial", child), { runId: "child" });
  projection.control(
    event("1", "", { ...child, attempt_id: "child-a", phase: "rollback" })
  );
  assert.deepEqual(
    parts.map((part) => part.text),
    ["Parent"]
  );
});

test("native final-answer tool preserves preceding public commentary", () => {
  const parts: any[] = [];
  const projection = createFinalAnswerProjection(parts);
  projection.message(event("1", "Here is the conclusion."));
  projection.apply(
    event("1", "Final result", {
      type: "final_answer",
      answer_phase: "complete",
    })
  );
  assert.deepEqual(
    parts.map((part) => part.text),
    ["Here is the conclusion.", "Final result"]
  );
});

test("legacy final-answer deltas and completion retain their existing single slot", () => {
  const parts: any[] = [];
  const projection = createFinalAnswerProjection(parts);
  projection.apply(
    event("1", "Answer", { type: "final_answer", answer_phase: "delta" })
  );
  projection.apply(
    event("1", "Answer", { type: "final_answer", answer_phase: "complete" })
  );
  assert.equal(parts.length, 1);
  assert.equal(parts[0].text, "Answer");
});
