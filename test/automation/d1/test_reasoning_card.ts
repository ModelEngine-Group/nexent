import assert from "node:assert/strict";
import test from "node:test";

import { createReasoningAccumulator } from "../../../frontend/lib/reasoningAccumulator.ts";

test("CMSR-D1-002 running label precedes retry content and survives rollback", () => {
  const parts: unknown[] = [];
  const reasoning = createReasoningAccumulator(parts);
  reasoning.queueStepLabel("**Step 1**\n");
  assert.equal((parts[0] as { text: string }).text, "**Step 1**\n");

  reasoning.beginAttempt("failed");
  reasoning.append("failed partial");
  reasoning.rollbackAttempt("failed");
  assert.equal((parts[0] as { text: string }).text, "**Step 1**\n");

  reasoning.beginAttempt("success");
  reasoning.append("<code>print(1)");
  assert.deepEqual(parts, [
    {
      type: "reasoning",
      text: "**Step 1**\n<code>print(1)",
      status: { type: "running" },
    },
  ]);
  reasoning.append("</code>");
  reasoning.commitAttempt("success");
  reasoning.close();
  assert.equal((parts[0] as { text: string }).text, "**Step 1**\n<code>print(1)</code>");
  assert.equal((parts[0] as { status: { type: string } }).status.type, "done");
});

test("CMSR-D1-002 historical label-only step is omitted", () => {
  const parts: unknown[] = [];
  const reasoning = createReasoningAccumulator(parts);
  reasoning.queueStepLabel("**Step 1**\n");
  assert.equal(parts.length, 1);
  reasoning.close();
  reasoning.queueStepLabel("**Step 2**\n");
  reasoning.append("<code>print(2)</code>");
  reasoning.close();
  assert.equal(parts.length, 1);
  assert.equal((parts[0] as { text: string }).text, "**Step 2**\n<code>print(2)</code>");
});

test("CMSR-D1-002 old history prepends a late label to existing reasoning", () => {
  const parts: unknown[] = [];
  const reasoning = createReasoningAccumulator(parts);
  reasoning.append("<code>print(1)</code>");
  reasoning.queueStepLabel("**Step 1**\n");
  reasoning.close();
  assert.equal(parts.length, 1);
  assert.equal((parts[0] as { text: string }).text, "**Step 1**\n<code>print(1)</code>");
});

test("CMSR-D1-002 whitespace and sibling output do not create phantom cards", () => {
  const parentParts: unknown[] = [];
  const siblingParts: unknown[] = [];
  const parent = createReasoningAccumulator(parentParts);
  const sibling = createReasoningAccumulator(siblingParts);
  parent.queueStepLabel("**Step 1**\n");
  parent.beginAttempt("parent-failed");
  parent.append("\n ");
  sibling.append("sibling thought");
  assert.equal((parentParts[0] as { text: string }).text, "**Step 1**\n");
  parent.rollbackAttempt("parent-failed");
  assert.equal((parentParts[0] as { text: string }).text, "**Step 1**\n");
  assert.equal((siblingParts[0] as { text: string }).text, "sibling thought");
  parent.append("<code>a = 1</code>");
  assert.equal((parentParts[0] as { text: string }).text, "**Step 1**\n<code>a = 1</code>");
});
