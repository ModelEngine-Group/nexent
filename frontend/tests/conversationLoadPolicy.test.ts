import assert from "node:assert/strict";
import test from "node:test";

import {
  isConversationListNearBottom,
  shouldContinueConversationPageLoading,
  shouldLoadNextConversationPage,
  // @ts-expect-error -- Node's built-in TypeScript runner needs the extension.
} from "../lib/conversationLoadPolicy.ts";

test("does not load without downward user intent", () => {
  assert.equal(
    shouldLoadNextConversationPage({
      hasMore: true,
      isLoading: false,
      isNearBottom: true,
      hasDownwardUserIntent: false,
    }),
    false
  );
});

test("loads once downward user intent reaches the bottom", () => {
  assert.equal(
    shouldLoadNextConversationPage({
      hasMore: true,
      isLoading: false,
      isNearBottom: true,
      hasDownwardUserIntent: true,
    }),
    true
  );
  assert.equal(isConversationListNearBottom(1000, 700, 220), true);
  assert.equal(isConversationListNearBottom(1000, 600, 220), false);
});

test("continues loading after a scrollbar jump only while pages make progress", () => {
  assert.equal(
    shouldContinueConversationPageLoading({
      hasMore: true,
      loadedBefore: 20,
      loadedAfter: 40,
      isNearLoadedBoundary: true,
    }),
    true
  );
  assert.equal(
    shouldContinueConversationPageLoading({
      hasMore: true,
      loadedBefore: 40,
      loadedAfter: 40,
      isNearLoadedBoundary: true,
    }),
    false
  );
});
