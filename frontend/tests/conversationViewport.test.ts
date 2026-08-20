import assert from "node:assert/strict";
import test from "node:test";

import {
  calculateConversationViewport,
  // @ts-ignore -- Node requires the extension for this standalone test.
} from "../lib/conversationViewport.ts";

test("calculates the exact initial rows and total virtual height", () => {
  const result = calculateConversationViewport({
    containerHeight: 500,
    rowHeight: 40,
    groupHeaderHeight: 28,
    groupGap: 16,
    groupCounts: [3, 7, 20],
  });

  assert.equal(result.initialLimit, 11);
  assert.equal(result.totalHeight, 30 * 40 + 3 * 28 + 2 * 16);
});

test("falls back to 20 when DOM measurements are invalid", () => {
  assert.equal(
    calculateConversationViewport({
      containerHeight: 0,
      rowHeight: 0,
      groupHeaderHeight: 0,
      groupCounts: [30, 0, 0],
    }).initialLimit,
    20
  );
});
