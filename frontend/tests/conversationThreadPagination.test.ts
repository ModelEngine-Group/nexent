import assert from "node:assert/strict";
import test from "node:test";

// @ts-expect-error Node's test runner loads the TypeScript source directly.
import { createConversationThreadPageLoader } from "../lib/conversationThreadPagination.ts";
// @ts-expect-error Node's test runner loads the TypeScript source directly.
import { runConversationDeletionLifecycle } from "../lib/conversationThreadPagination.ts";
import {
  calculateConversationVirtualSpacerHeight,
  calculateConversationViewport,
  ConversationViewportCoordinator,
  // @ts-expect-error Node's test runner loads the TypeScript source directly.
} from "../lib/conversationViewport.ts";

interface Item {
  id: string;
}

interface TestMetadata {
  total: number;
  today: number;
  last_7_days: number;
  older: number;
}

const createItems = (count: number): Item[] =>
  Array.from({ length: count }, (_, index) => ({ id: String(index + 1) }));

const createLoaderHarness = (initialItems: Item[], pageSize = 20) => {
  let items = initialItems;
  const calls: Array<{ offset: number; limit: number }> = [];
  const coordinator = new ConversationViewportCoordinator();
  const loader = createConversationThreadPageLoader<Item, string, TestMetadata>(
    {
      pageSize,
      takeNextPageSize: coordinator.takeNextPageSize,
      getOffsetAdjustment: coordinator.getOffsetAdjustment,
      commitOffsetAdjustment: coordinator.commitOffsetAdjustment,
      resetPagination: coordinator.resetPagination,
      fetchPage: async (params) => {
        calls.push(params);
        return {
          items: items.slice(params.offset, params.offset + params.limit),
          metadata: {
            total: items.length,
            today: items.length,
            last_7_days: 0,
            older: 0,
          },
        };
      },
      mapItem: (item) => item.id,
      onMetadata: coordinator.setMetadata,
    }
  );

  return {
    calls,
    coordinator,
    loader,
    deleteItem(id: string) {
      items = items.filter((item) => item.id !== id);
    },
  };
};

test("successful deletion updates pagination state after the final page is loaded", async () => {
  const events: string[] = [];
  const coordinator = new ConversationViewportCoordinator();

  await runConversationDeletionLifecycle({
    pendingPageLoad: Promise.resolve().then(() => {
      events.push("page-loaded");
    }),
    deleteConversation: async () => {
      events.push("deleted");
    },
    recordDeletedLoadedItem: () => {
      coordinator.recordDeletedLoadedItem();
      events.push("pagination-updated");
    },
  });

  assert.deepEqual(events, ["page-loaded", "deleted", "pagination-updated"]);
  assert.equal(coordinator.getOffsetAdjustment(), 1);
  assert.equal(
    calculateConversationVirtualSpacerHeight({
      totalCount: 5,
      pendingDeletionCount: coordinator.getOffsetAdjustment(),
      loadedContentHeight: 4 * 36 + 32,
      rowHeight: 36,
      groupHeaderHeight: 32,
      groupCount: 1,
      contentPadding: 16,
    }),
    0
  );
});

test("failed deletion does not update pagination state", async () => {
  let recordedDeletion = false;

  await assert.rejects(
    runConversationDeletionLifecycle({
      pendingPageLoad: null,
      deleteConversation: async () => {
        throw new Error("delete failed");
      },
      recordDeletedLoadedItem: () => {
        recordedDeletion = true;
      },
    }),
    /delete failed/
  );

  assert.equal(recordedDeletion, false);
});

test("bootstrap waits for viewport measurement before fetching the first page", async () => {
  const harness = createLoaderHarness(createItems(8), 3);

  assert.deepEqual(await harness.loader(), {
    threads: [],
    nextCursor: "0",
  });
  assert.deepEqual(harness.calls, []);

  harness.coordinator.requestNextPageSize(5);
  assert.deepEqual(await harness.loader({ after: "0" }), {
    threads: ["1", "2", "3", "4", "5"],
    nextCursor: "5",
  });
  assert.deepEqual(harness.calls, [{ offset: 0, limit: 5 }]);
});

test("later pages use the actual cursor and a one-shot requested size", async () => {
  const harness = createLoaderHarness(createItems(10), 3);
  await harness.loader();

  harness.coordinator.requestNextPageSize(2);
  const first = await harness.loader({ after: "0" });
  harness.coordinator.requestNextPageSize(4);
  const second = await harness.loader({ after: first.nextCursor });
  const third = await harness.loader({ after: second.nextCursor });

  assert.deepEqual(first.threads, ["1", "2"]);
  assert.deepEqual(second.threads, ["3", "4", "5", "6"]);
  assert.deepEqual(third.threads, ["7", "8", "9"]);
  assert.deepEqual(harness.calls, [
    { offset: 0, limit: 2 },
    { offset: 2, limit: 4 },
    { offset: 6, limit: 3 },
  ]);
});

test("small-window deletion preserves loaded pages and corrects the next offset", async () => {
  const harness = createLoaderHarness(createItems(46));
  const visibleThreads: string[] = [];
  const measuredViewport = calculateConversationViewport({
    containerHeight: 540,
    rowHeight: 36,
    groupHeaderHeight: 32,
    contentPadding: 16,
    groupCounts: [46, 0, 0],
  });

  // Runtime bootstrap happens before the sidebar DOM exists. The mounted
  // sidebar then measures the small viewport and requests its real first page.
  await harness.loader();
  harness.coordinator.requestNextPageSize(measuredViewport.initialLimit);
  let page = await harness.loader({ after: "0" });
  visibleThreads.push(...page.threads);
  page = await harness.loader({ after: page.nextCursor });
  visibleThreads.push(...page.threads);

  assert.equal(visibleThreads.length, 34);
  assert.equal(page.nextCursor, "34");

  // assistant-ui removes the item optimistically. Resizing must not reload or
  // discard the other loaded rows; only the deleted row leaves the list.
  harness.deleteItem("4");
  visibleThreads.splice(visibleThreads.indexOf("4"), 1);
  harness.coordinator.recordDeletedLoadedItem();

  assert.equal(visibleThreads.length, 33);
  assert.equal(harness.calls.length, 2);

  const finalPage = await harness.loader({ after: page.nextCursor });
  visibleThreads.push(...finalPage.threads);

  assert.deepEqual(harness.calls.at(-1), { offset: 33, limit: 20 });
  assert.equal(finalPage.nextCursor, undefined);
  assert.deepEqual(
    visibleThreads,
    createItems(46)
      .filter((item) => item.id !== "4")
      .map((item) => item.id)
  );
  assert.equal(new Set(visibleThreads).size, 45);
});

test("multiple successful deletions are applied to the next page once", async () => {
  const harness = createLoaderHarness(createItems(60));
  await harness.loader();
  harness.coordinator.requestNextPageSize(20);
  const first = await harness.loader({ after: "0" });

  harness.deleteItem("2");
  harness.deleteItem("8");
  harness.coordinator.recordDeletedLoadedItem();
  harness.coordinator.recordDeletedLoadedItem();

  const second = await harness.loader({ after: first.nextCursor });
  const third = await harness.loader({ after: second.nextCursor });

  assert.deepEqual(harness.calls, [
    { offset: 0, limit: 20 },
    { offset: 18, limit: 20 },
    { offset: 38, limit: 20 },
  ]);
  assert.equal(harness.coordinator.getOffsetAdjustment(), 0);
  assert.equal(third.nextCursor, undefined);
});

test("a failed page request retains the deletion offset for retry", async () => {
  const coordinator = new ConversationViewportCoordinator();
  let attempts = 0;
  const calls: Array<{ offset: number; limit: number }> = [];
  const loader = createConversationThreadPageLoader<Item, string>({
    pageSize: 20,
    takeNextPageSize: coordinator.takeNextPageSize,
    getOffsetAdjustment: coordinator.getOffsetAdjustment,
    commitOffsetAdjustment: coordinator.commitOffsetAdjustment,
    resetPagination: coordinator.resetPagination,
    fetchPage: async (params) => {
      calls.push(params);
      attempts += 1;
      if (attempts === 1) throw new Error("temporary failure");
      return { items: [{ id: "20" }], metadata: { total: 20 } };
    },
    mapItem: (item) => item.id,
    onMetadata: () => undefined,
  });

  coordinator.recordDeletedLoadedItem();
  await assert.rejects(loader({ after: "20" }), /temporary failure/);
  assert.equal(coordinator.getOffsetAdjustment(), 1);

  assert.deepEqual(await loader({ after: "20" }), {
    threads: ["20"],
    nextCursor: undefined,
  });
  assert.deepEqual(calls, [
    { offset: 19, limit: 20 },
    { offset: 19, limit: 20 },
  ]);
  assert.equal(coordinator.getOffsetAdjustment(), 0);
});

test("invalid cursors restart from offset zero without consuming deletion state", async () => {
  const harness = createLoaderHarness([], 20);
  harness.coordinator.recordDeletedLoadedItem();

  await harness.loader({ after: "invalid" });
  await harness.loader({ after: String(Number.MAX_SAFE_INTEGER) });

  assert.deepEqual(harness.calls, [
    { offset: 0, limit: 20 },
    { offset: 0, limit: 20 },
  ]);
  assert.equal(harness.coordinator.getOffsetAdjustment(), 1);
});
