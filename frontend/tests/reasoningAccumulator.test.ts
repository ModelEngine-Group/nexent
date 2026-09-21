import assert from "node:assert/strict";
import test from "node:test";
// @ts-expect-error -- Node's built-in TypeScript runner needs the extension.
import { createReasoningAccumulator } from "../lib/reasoningAccumulator.ts";
const appendDisplayPart = (parts: unknown[], content: unknown) =>
  parts.push({ type: "data", name: "example", data: content });
const display = (id: string) => ({ id, text: "Example display content" });

test("display content leaves an unfinished sentence in one growing reasoning card", () => {
  const parts: unknown[] = [];
  const reasoning = createReasoningAccumulator(parts);
  reasoning.append("让我先构建图表数据（这是");
  const previousSnapshot = [...parts];
  appendDisplayPart(parts, display("one"));
  reasoning.append("演示用数据）。");
  appendDisplayPart(parts, display("two"));
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

test("a real tool boundary ends the card and keeps later reasoning after display content", () => {
  const parts: unknown[] = [];
  const reasoning = createReasoningAccumulator(parts);
  reasoning.append("Choose the palette.");
  appendDisplayPart(parts, display("one"));
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
  appendDisplayPart(parts, display("one"));
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

test("empty reasoning cannot move display content received before the model starts", () => {
  const parts: unknown[] = [];
  const reasoning = createReasoningAccumulator(parts);
  reasoning.append("");
  reasoning.close();
  appendDisplayPart(parts, display("one"));
  reasoning.append("Use the requested palette.");
  reasoning.close();
  assert.deepEqual(
    parts.map((part) => (part as { type: string }).type),
    ["data", "reasoning"]
  );
});

test("CMSR-003 rollback removes only the failed model attempt", () => {
  const parts: unknown[] = [];
  const reasoning = createReasoningAccumulator(parts);
  reasoning.append("stable prefix");
  reasoning.beginAttempt("attempt-one");
  reasoning.append(" leaked partial");
  reasoning.rollbackAttempt("attempt-one");

  assert.deepEqual(parts, [
    {
      type: "reasoning",
      text: "stable prefix",
      status: { type: "running" },
    },
  ]);

  reasoning.beginAttempt("attempt-two");
  reasoning.append(" recovered");
  reasoning.commitAttempt("attempt-two");
  assert.equal((parts[0] as { text: string }).text, "stable prefix recovered");
});

test("CMSR-003 rollback preserves interleaved sibling output", () => {
  const parts: unknown[] = [];
  const reasoning = createReasoningAccumulator(parts);
  reasoning.append("parent prefix");
  reasoning.beginAttempt("parent-attempt");
  reasoning.append(" leaked parent token");

  const sibling = { type: "reasoning", text: "sibling output" };
  parts.unshift(sibling);
  reasoning.rollbackAttempt("parent-attempt");

  assert.deepEqual(parts, [
    sibling,
    {
      type: "reasoning",
      text: "parent prefix",
      status: { type: "running" },
    },
  ]);
});

test("a new model step starts below display content even when no tool ran", () => {
  const parts: unknown[] = [];
  const reasoning = createReasoningAccumulator(parts);
  reasoning.append("Step 1: original thought");
  appendDisplayPart(parts, display("one"));
  reasoning.append(" completed.");
  reasoning.close();
  reasoning.append("Step 2: incorporate the display content.");
  assert.deepEqual(parts[0], {
    type: "reasoning",
    text: "Step 1: original thought completed.",
    status: { type: "done" },
  });
  assert.deepEqual(parts[2], {
    type: "reasoning",
    text: "Step 2: incorporate the display content.",
    status: { type: "running" },
  });
});

test("persisted token batches restore the same card order as live streaming", () => {
  const project = (chunks: Array<[string, string]>) => {
    const parts: unknown[] = [];
    const reasoning = createReasoningAccumulator(parts);
    for (const [type, content] of chunks) {
      if (type === "display") appendDisplayPart(parts, content);
      else if (type === "final_answer") {
        reasoning.close();
        parts.push({ type: "text", text: content });
      } else reasoning.append(content);
    }
    reasoning.close();
    return parts;
  };
  const input = JSON.stringify(display("one"));
  const live = project([
    ["reasoning", "先构建"],
    ["reasoning", "数据（这是"],
    ["display", input],
    ["reasoning", "演示"],
    ["reasoning", "数据）。"],
    ["final_answer", "已完成。"],
  ]);
  const history = project([
    ["reasoning", "先构建数据（这是"],
    ["display", input],
    ["reasoning", "演示数据）。"],
    ["final_answer", "已完成。"],
  ]);
  assert.deepEqual(history, live);
  assert.deepEqual(
    history.map((part) => (part as { type: string }).type),
    ["reasoning", "data", "text"]
  );
});
