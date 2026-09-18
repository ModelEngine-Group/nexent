import assert from "node:assert/strict";
import test from "node:test";
// @ts-expect-error -- Node's built-in TypeScript runner needs the extension.
import { createReasoningAccumulator } from "../lib/reasoningAccumulator.ts";
// @ts-expect-error -- Node's built-in TypeScript runner needs the extension.
import { appendGuidanceMessage } from "../features/humanInteraction/guidanceMessage.ts";

const guidance = (id: string) => ({
  request_id: id,
  text: "要求使用华为红色",
  created_at: "2026-09-14T10:50:00Z",
});

test("guidance leaves an unfinished sentence in one growing reasoning card", () => {
  const parts: unknown[] = [];
  const reasoning = createReasoningAccumulator(parts);
  reasoning.append("让我先构建图表数据（这是");
  const previousSnapshot = [...parts];
  appendGuidanceMessage(parts, guidance("one"));
  reasoning.append("演示用数据）。");
  appendGuidanceMessage(parts, guidance("two"));
  reasoning.append("先调用图表生成工具。");

  assert.deepEqual(parts[0], {
    type: "reasoning",
    text: "让我先构建图表数据（这是演示用数据）。先调用图表生成工具。",
    status: { type: "running" },
  });
  assert.equal(parts.length, 3);
  assert.deepEqual(previousSnapshot[0], {
    type: "reasoning",
    text: "让我先构建图表数据（这是",
    status: { type: "running" },
  });
});

test("a real tool boundary ends the card and keeps later reasoning after guidance", () => {
  const parts: unknown[] = [];
  const reasoning = createReasoningAccumulator(parts);
  reasoning.append("Choose the palette.");
  appendGuidanceMessage(parts, guidance("one"));
  reasoning.close();
  parts.push({ type: "tool-call", toolName: "generate_chart" });
  reasoning.append("Review the chart.");
  reasoning.close();
  reasoning.close();
  assert.deepEqual(
    parts.map((part) => (part as { type: string }).type),
    ["reasoning", "data", "tool-call", "reasoning"]
  );
  assert.deepEqual(parts[0], {
    type: "reasoning",
    text: "Choose the palette.",
    status: { type: "done" },
  });
  assert.deepEqual(parts[3], {
    type: "reasoning",
    text: "Review the chart.",
    status: { type: "done" },
  });
});

test("reasoning updates its own part after another display part is removed", () => {
  const parts: unknown[] = [{ type: "data", name: "history-summary" }];
  const reasoning = createReasoningAccumulator(parts);
  reasoning.append("First ");
  appendGuidanceMessage(parts, guidance("one"));
  parts.splice(0, 1);
  reasoning.append("second");
  reasoning.close();
  assert.deepEqual(parts[0], {
    type: "reasoning",
    text: "First second",
    status: { type: "done" },
  });
  assert.equal(parts.length, 2);
});

test("empty reasoning cannot move guidance received before the model starts", () => {
  const parts: unknown[] = [];
  const reasoning = createReasoningAccumulator(parts);
  reasoning.append("");
  reasoning.close();
  appendGuidanceMessage(parts, guidance("one"));
  reasoning.append("Use the requested palette.");
  reasoning.close();
  assert.deepEqual(
    parts.map((part) => (part as { type: string }).type),
    ["data", "reasoning"]
  );
});

test("a new model step starts below guidance even when no tool ran", () => {
  const parts: unknown[] = [];
  const reasoning = createReasoningAccumulator(parts);
  reasoning.append("Step 1: original thought");
  appendGuidanceMessage(parts, guidance("one"));
  reasoning.append(" completed.");
  reasoning.close();
  reasoning.append("Step 2: incorporate the guidance.");
  assert.deepEqual(parts[0], {
    type: "reasoning",
    text: "Step 1: original thought completed.",
    status: { type: "done" },
  });
  assert.deepEqual(parts[2], {
    type: "reasoning",
    text: "Step 2: incorporate the guidance.",
    status: { type: "running" },
  });
});

test("persisted token batches restore the same card order as live streaming", () => {
  const project = (chunks: Array<[string, string]>) => {
    const parts: unknown[] = [];
    const reasoning = createReasoningAccumulator(parts);
    for (const [type, content] of chunks) {
      if (type === "user_steering") appendGuidanceMessage(parts, content);
      else if (type === "final_answer") {
        reasoning.close();
        parts.push({ type: "text", text: content });
      } else reasoning.append(content);
    }
    reasoning.close();
    return parts;
  };
  const input = JSON.stringify(guidance("one"));
  const live = project([
    ["reasoning", "先构建"],
    ["reasoning", "数据（这是"],
    ["user_steering", input],
    ["reasoning", "演示"],
    ["reasoning", "数据）。"],
    ["final_answer", "已完成。"],
  ]);
  const history = project([
    ["reasoning", "先构建数据（这是"],
    ["user_steering", input],
    ["reasoning", "演示数据）。"],
    ["final_answer", "已完成。"],
  ]);
  assert.deepEqual(history, live);
  assert.deepEqual(
    history.map((part) => (part as { type: string }).type),
    ["reasoning", "data", "text"]
  );
});
