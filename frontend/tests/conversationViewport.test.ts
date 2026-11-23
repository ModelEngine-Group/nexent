import assert from "node:assert/strict";
import test from "node:test";

import {
  calculateConversationViewport,
  ConversationViewportCoordinator,
  getConversationViewportGroupCounts,
  // @ts-expect-error -- Node requires the extension for this standalone test.
} from "../lib/conversationViewport.ts";

test("requests enough rows to fill the viewport before metadata is loaded", () => {
  const groupCounts = getConversationViewportGroupCounts();
  const result = calculateConversationViewport({
    containerHeight: 500,
    rowHeight: 40,
    groupHeaderHeight: 28,
    groupGap: 16,
    contentPadding: 16,
    groupCounts,
  });

  assert.deepEqual(groupCounts, [100, 0, 0]);
  assert.equal(result.initialLimit, 12);
});

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

test("publishes metadata and consumes the dynamic first-page limit once", () => {
  const coordinator = new ConversationViewportCoordinator();
  let notifications = 0;
  const unsubscribe = coordinator.subscribe(() => {
    notifications += 1;
  });

  coordinator.setMetadata({
    total: 35,
    today: 5,
    last_7_days: 10,
    older: 20,
  });
  coordinator.resolveInitialLimit(29);

  assert.equal(notifications, 1);
  assert.equal(coordinator.getSnapshot()?.total, 35);
  assert.equal(coordinator.takePageLimit(), 29);
  assert.equal(coordinator.takePageLimit(), 20);
  coordinator.reset();
  assert.equal(coordinator.getSnapshot(), null);
  assert.equal(notifications, 2);
  unsubscribe();
});
