// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import assert from "node:assert/strict";
import test from "node:test";
// @ts-expect-error -- Node's built-in TypeScript runner needs the extension.
import { createFinalAnswerProjection } from "../lib/finalAnswerProjection.ts";

const event = (step_id: string, content: string, extra = {}) => ({
  type: "model_output_thinking",
  step_id,
  content,
  ...extra,
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

test("legacy text events promote only the final native step and preserve provider reasoning", () => {
  const earlier = { type: "reasoning", text: "Checking files." };
  const tool = { type: "tool-call", toolName: "list_directory" };
  const last = { type: "reasoning", text: "Provider reasoning.Final answer" };
  const parts: any[] = [earlier, tool, last];
  const projection = createFinalAnswerProjection(parts);

  projection.recordReasoning(event("1", earlier.text, { type: "model_output_thinking" }), earlier);
  projection.recordReasoning(event("2", "Provider reasoning.", { type: "model_output_deep_thinking" }), last);
  projection.recordReasoning(event("2", "Final answer", { type: "model_output_thinking" }), last);
  projection.apply(event("2", "Final answer", {
    type: "final_answer",
    answer_phase: "complete",
    reclassify_step: true,
  }));

  assert.equal(parts.length, 4);
  assert.equal(parts[0], earlier);
  assert.equal(parts[1], tool);
  assert.equal(parts[2].text, "Provider reasoning.");
  assert.equal(parts[3].text, "Final answer");
  assert.equal(parts[3].isFinalAnswer, true);
});
