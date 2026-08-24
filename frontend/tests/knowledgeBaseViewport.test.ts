import assert from "node:assert/strict";
import test from "node:test";

import {
  calculateKnowledgeBaseInitialLimit,
  createKnowledgeBaseFilterKey,
  // @ts-expect-error -- Node requires the extension for this standalone test.
} from "../lib/knowledgeBaseViewport.ts";

test("rounds the initial knowledge base count up to fill the viewport", () => {
  assert.equal(calculateKnowledgeBaseInitialLimit(721, 112), 7);
  assert.equal(calculateKnowledgeBaseInitialLimit(721, 90), 9);
});

test("uses safe bounds for invalid or unusually large viewports", () => {
  assert.equal(calculateKnowledgeBaseInitialLimit(0, 112), 1);
  assert.equal(calculateKnowledgeBaseInitialLimit(100000, 10), 100);
});

test("keeps the filter key stable until the filters actually change", () => {
  const initialKey = createKnowledgeBaseFilterKey("", [], []);

  assert.equal(createKnowledgeBaseFilterKey("", [], []), initialKey);
  assert.notEqual(createKnowledgeBaseFilterKey("medical", [], []), initialKey);
  assert.notEqual(createKnowledgeBaseFilterKey("", ["nexent"], []), initialKey);
  assert.notEqual(
    createKnowledgeBaseFilterKey("", [], ["embedding-model"]),
    initialKey
  );
});
