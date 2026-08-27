import assert from "node:assert/strict";
import test from "node:test";

import {
  calculateConversationVirtualSpacerHeight,
  calculateConversationViewport,
  ConversationViewportCoordinator,
  getConversationViewportGroupCounts,
  isConversationLoadedBoundaryReached,
  // @ts-expect-error Node's test runner loads the TypeScript source directly.
} from "../lib/conversationViewport.ts";

test("keeps the native scroll height stable before and after pagination", () => {
  const cases = [
    { clientHeight: 505, loadedCount: 13 },
    { clientHeight: 1067, loadedCount: 29 },
  ];

  for (const { clientHeight, loadedCount } of cases) {
    const loadedContentHeight = loadedCount * 36 + 2 * 32;
    const spacerHeight = calculateConversationVirtualSpacerHeight({
      totalCount: 37,
      pendingDeletionCount: 0,
      loadedContentHeight,
      rowHeight: 36,
      groupHeaderHeight: 32,
      groupCount: 2,
      contentPadding: 16,
    });
    const initialScrollHeight = 16 + loadedContentHeight + 1 + spacerHeight;
    const fullyLoadedScrollHeight = 16 + (37 * 36 + 2 * 32) + 1;

    assert.equal(initialScrollHeight, fullyLoadedScrollHeight);
    assert.ok(initialScrollHeight > clientHeight);
  }
});

test("keeps virtual height continuous after deleting a loaded conversation", () => {
  const loadedContentHeightAfterDelete = 28 * 36 + 2 * 32;
  const spacerHeight = calculateConversationVirtualSpacerHeight({
    totalCount: 37,
    pendingDeletionCount: 1,
    loadedContentHeight: loadedContentHeightAfterDelete,
    rowHeight: 36,
    groupHeaderHeight: 32,
    groupCount: 2,
    contentPadding: 16,
  });

  assert.equal(spacerHeight, 8 * 36);
  assert.equal(
    16 + loadedContentHeightAfterDelete + 1 + spacerHeight,
    16 + (36 * 36 + 2 * 32) + 1
  );
});

test("loads against the real loaded-content boundary, not the virtual tail", () => {
  assert.equal(
    isConversationLoadedBoundaryReached({
      scrollTop: 0,
      clientHeight: 505,
      loadedBoundary: 549,
    }),
    false
  );
  assert.equal(
    isConversationLoadedBoundaryReached({
      scrollTop: 44,
      clientHeight: 505,
      loadedBoundary: 549,
    }),
    true
  );
  assert.equal(
    isConversationLoadedBoundaryReached({
      scrollTop: 44,
      clientHeight: 505,
      loadedBoundary: 1269,
    }),
    false
  );
});

test("calculates rows from data-source group counts and includes overflow", () => {
  assert.deepEqual(
    calculateConversationViewport({
      containerHeight: 188,
      rowHeight: 36,
      groupHeaderHeight: 24,
      contentPadding: 16,
      groupCounts: [2, 3, 5],
    }),
    { initialLimit: 4, totalHeight: 448 }
  );
});

test("measured first-page size follows small and large viewport heights", () => {
  for (const containerHeight of [360, 900]) {
    const viewport = calculateConversationViewport({
      containerHeight,
      rowHeight: 36,
      groupHeaderHeight: 32,
      contentPadding: 16,
      groupCounts: [100, 0, 0],
    });
    const renderedHeight = 16 + 32 + viewport.initialLimit * 36;

    assert.ok(renderedHeight > containerHeight);
    assert.ok(renderedHeight - 36 <= containerHeight);
  }
});

test("uses metadata counts without reordering conversations in memory", () => {
  assert.deepEqual(
    getConversationViewportGroupCounts({
      total: 8,
      today: 2,
      last_7_days: 3,
      older: 3,
    }),
    [2, 3, 3]
  );
});

test("coordinator consumes measured page sizes once", () => {
  const coordinator = new ConversationViewportCoordinator();
  coordinator.requestNextPageSize(6.1);
  assert.equal(coordinator.takeNextPageSize(20), 7);
  assert.equal(coordinator.takeNextPageSize(20), 20);

  coordinator.requestNextPageSize(5);
  coordinator.clearNextPageSize();
  assert.equal(coordinator.takeNextPageSize(20), 20);
});

test("coordinator publishes metadata without changing pagination state", () => {
  const coordinator = new ConversationViewportCoordinator();
  let notifications = 0;
  const unsubscribe = coordinator.subscribe(() => {
    notifications += 1;
  });
  const metadata = {
    total: 3,
    today: 1,
    last_7_days: 1,
    older: 1,
  };

  coordinator.setMetadata(metadata);

  assert.equal(coordinator.getSnapshot(), metadata);
  assert.equal(notifications, 1);
  unsubscribe();
});

test("reset clears transient pagination state and published metadata", () => {
  const coordinator = new ConversationViewportCoordinator();
  let notifications = 0;
  coordinator.subscribe(() => {
    notifications += 1;
  });

  coordinator.requestNextPageSize(7);
  coordinator.recordDeletedLoadedItem();
  coordinator.setMetadata({
    total: 3,
    today: 3,
    last_7_days: 0,
    older: 0,
  });
  coordinator.resetPagination();

  assert.equal(coordinator.getSnapshot(), null);
  assert.equal(coordinator.getOffsetAdjustment(), 0);
  assert.equal(coordinator.takeNextPageSize(20), 20);
  assert.equal(notifications, 2);
});
