import assert from "node:assert/strict";
import test from "node:test";

import {
  createConversationTitleRequest,
  ConversationTitleGuard,
  // @ts-expect-error -- Node's built-in TypeScript runner needs the extension.
} from "../lib/conversationTitle.ts";

test("uses the model snapshot associated with the agent run", () => {
  let selectedModelId: number | null = 7;
  const modelIdForRun = selectedModelId;
  const request = createConversationTitleRequest(42, "Question", modelIdForRun);

  selectedModelId = 9;

  assert.equal(selectedModelId, 9);
  assert.deepEqual(request, {
    conversation_id: 42,
    question: "Question",
    model_id: 7,
  });
});

test("omits model_id for legacy default-model behavior", () => {
  assert.deepEqual(createConversationTitleRequest(42, "Question", null), {
    conversation_id: 42,
    question: "Question",
  });
});

test("late automatic results are rejected after a manual rename", () => {
  const guard = new ConversationTitleGuard();
  const revision = guard.capture("thread-a");
  assert.equal(guard.isCurrent("thread-a", revision), true);
  guard.renamed("thread-a");
  assert.equal(guard.isCurrent("thread-a", revision), false);
  // Another conversation and a subsequent request remain independent.
  assert.equal(guard.isCurrent("thread-b", 0), true);
  assert.equal(guard.isCurrent("thread-a", guard.capture("thread-a")), true);
});
