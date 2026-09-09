import assert from "node:assert/strict";
import test from "node:test";

import {
  completeTrailingToolCalls,
  // @ts-expect-error -- Node's built-in TypeScript runner needs the extension.
} from "../lib/toolCallStatus.ts";

test("completes every running tool in the finished ReAct code block", () => {
  const earlierTool = { type: "tool-call", status: { type: "running" } };
  const parts = [
    earlierTool,
    { type: "reasoning", text: "next code block" },
    { type: "tool-call", status: { type: "running" } },
    { type: "tool-call" },
    { type: "tool-call", status: { type: "incomplete", reason: "cancelled" } },
  ];

  completeTrailingToolCalls(parts);

  assert.deepEqual(parts[2].status, { type: "complete" });
  assert.deepEqual(parts[3].status, { type: "complete" });
  assert.deepEqual(parts[4].status, { type: "incomplete", reason: "cancelled" });
  assert.deepEqual(earlierTool.status, { type: "running" });
});
