import assert from "node:assert/strict";
import test from "node:test";

import {
  getConversationPageRequest,
  isConversationListNearBottom,
  shouldRequestConversationPageFromScroll,
  shouldLoadNextConversationPage,
  // @ts-expect-error Node's test runner loads the TypeScript source directly.
} from "../lib/conversationLoadPolicy.ts";

test("requests only the rows missing from an underfilled viewport", () => {
  assert.deepEqual(
    getConversationPageRequest({
      hasMore: true,
      isLoading: false,
      clientHeight: 600,
      scrollHeight: 420,
      rowHeight: 36,
      isLoadRequested: false,
      regularPageSize: 20,
    }),
    { limit: 6, reason: "viewport-fill" }
  );
});

test("loads one overflow row when content exactly fills the viewport", () => {
  assert.deepEqual(
    getConversationPageRequest({
      hasMore: true,
      isLoading: false,
      clientHeight: 600,
      scrollHeight: 600,
      rowHeight: 36,
      isLoadRequested: false,
      regularPageSize: 20,
    }),
    { limit: 1, reason: "viewport-fill" }
  );
});

test("uses the regular page size for an explicit user pagination request", () => {
  assert.deepEqual(
    getConversationPageRequest({
      hasMore: true,
      isLoading: false,
      clientHeight: 600,
      scrollHeight: 1200,
      rowHeight: 36,
      isLoadRequested: true,
      regularPageSize: 20,
    }),
    { limit: 20, reason: "scroll" }
  );
});

test("does not preload a second page when the initial overflow row is below the viewport", () => {
  assert.equal(
    getConversationPageRequest({
      hasMore: true,
      isLoading: false,
      clientHeight: 600,
      scrollHeight: 636,
      rowHeight: 36,
      isLoadRequested: false,
      regularPageSize: 20,
    }),
    null
  );
});

test("does not request while loading, exhausted, or away from the sentinel", () => {
  const base = {
    hasMore: true,
    isLoading: false,
    clientHeight: 600,
    scrollHeight: 1200,
    rowHeight: 36,
    isLoadRequested: false,
    regularPageSize: 20,
  };

  assert.equal(getConversationPageRequest({ ...base, isLoading: true }), null);
  assert.equal(getConversationPageRequest({ ...base, hasMore: false }), null);
  assert.equal(getConversationPageRequest(base), null);
});

test("legacy scroll guards remain stable", () => {
  assert.equal(isConversationListNearBottom(1000, 720, 200), true);
  assert.equal(
    shouldLoadNextConversationPage({
      hasMore: true,
      isLoading: false,
      isNearBottom: true,
    }),
    true
  );
});

test("small viewports request the next page when scrolling near the post-delete bottom", () => {
  const state = {
    hasMore: true,
    isLoading: false,
    scrollHeight: 720,
    scrollTop: 280,
    clientHeight: 360,
    hasUserIntent: true,
    isScrollingDown: true,
  };

  assert.equal(shouldRequestConversationPageFromScroll(state), true);
  assert.equal(
    shouldRequestConversationPageFromScroll({ ...state, scrollTop: 100 }),
    false
  );
  assert.equal(
    shouldRequestConversationPageFromScroll({ ...state, isLoading: true }),
    false
  );
  assert.equal(
    shouldRequestConversationPageFromScroll({ ...state, hasMore: false }),
    false
  );
});

test("does not treat layout changes or upward scrolling as pagination intent", () => {
  const state = {
    hasMore: true,
    isLoading: false,
    scrollHeight: 720,
    scrollTop: 280,
    clientHeight: 360,
    hasUserIntent: false,
    isScrollingDown: true,
  };

  assert.equal(shouldRequestConversationPageFromScroll(state), false);
  assert.equal(
    shouldRequestConversationPageFromScroll({
      ...state,
      hasUserIntent: true,
      isScrollingDown: false,
    }),
    false
  );
});
