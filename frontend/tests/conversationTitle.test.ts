import assert from "node:assert/strict";
import test from "node:test";

import {
  createConversationTitleRequest,
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
