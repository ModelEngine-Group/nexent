import assert from "node:assert/strict";
import test from "node:test";

import {
  completeTrailingToolCalls,
  // @ts-expect-error -- Node's built-in TypeScript runner needs the extension.
} from "../lib/toolCallStatus.ts";

type TestToolCall = {
  type: string;
  status?: { type: string; reason?: string };
  result?: unknown;
};

test("completes every running tool in the finished ReAct code block", () => {
  const earlierTool: TestToolCall = {
    type: "tool-call",
    status: { type: "running" },
  };
  const parts: TestToolCall[] = [
    earlierTool,
    { type: "reasoning", status: { type: "complete" } },
    { type: "tool-call", status: { type: "running" } },
    { type: "tool-call" },
    { type: "tool-call", status: { type: "incomplete", reason: "cancelled" } },
  ];

  completeTrailingToolCalls(parts);

  assert.deepEqual(parts[2].status, { type: "complete" });
  assert.deepEqual(parts[3].status, { type: "complete" });
  assert.equal(parts[2].result, "");
  assert.equal(parts[3].result, "");
  assert.deepEqual(parts[4].status, { type: "incomplete", reason: "cancelled" });
  assert.equal(parts[4].result, undefined);
  assert.deepEqual(earlierTool.status, { type: "running" });
  assert.equal(earlierTool.result, undefined);
});
