import assert from "node:assert/strict";
import test from "node:test";

import {
  buildHistoricalMessageTiming,
  // @ts-expect-error -- Node's built-in TypeScript runner needs the extension.
} from "../lib/messageTiming.ts";

test("builds total timing from persisted token-count steps", () => {
  assert.deepEqual(
    buildHistoricalMessageTiming([
      { duration: 1.25, totalOutputTokens: 100 },
      { duration: 0.75, totalOutputTokens: 160 },
    ]),
    {
      streamStartTime: 0,
      totalStreamTime: 2000,
      tokenCount: 160,
      tokensPerSecond: 80,
      totalChunks: 1,
      toolCallCount: 0,
    }
  );
});

test("omits timing when persisted token-count steps have no duration", () => {
  assert.equal(
    buildHistoricalMessageTiming([
      { duration: 0, totalOutputTokens: 100 },
      { duration: -1, totalOutputTokens: 160 },
    ]),
    undefined
  );
});
