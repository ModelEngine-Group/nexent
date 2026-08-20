import assert from "node:assert/strict";
import test from "node:test";

import {
  isConversationListNearBottom,
  shouldLoadNextConversationPage,
  // @ts-ignore -- Node's built-in TypeScript runner needs the extension.
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
