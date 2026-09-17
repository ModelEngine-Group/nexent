import assert from "node:assert/strict";
import test from "node:test";

import type { Document } from "../types/knowledgeBase.ts";
// @ts-expect-error -- Node requires the extension for this standalone test.
import { areDocumentsEqual } from "../lib/documentStateUtils.ts";

const createDocument = (overrides: Partial<Document> = {}): Document => ({
  id: "document-1",
  kb_id: "kb-1",
  name: "example.txt",
  type: "text/plain",
  size: 12,
  create_time: "2026-09-17T00:00:00Z",
  chunk_num: 2,
  token_num: 10,
  status: "DONE",
  latest_task_id: "task-1",
  ...overrides,
});

test("treats equivalent polling snapshots as equal", () => {
  const current = [createDocument({ selected: true })];
  const next = [createDocument({ selected: false })];

  assert.equal(areDocumentsEqual(current, next), true);
});

test("detects document status and progress changes", () => {
  const current = [createDocument({ status: "PROCESSING" })];
  const next = [
    createDocument({
      status: "DONE",
      processed_chunk_num: 2,
      total_chunk_num: 2,
    }),
  ];

  assert.equal(areDocumentsEqual(current, next), false);
});

test("detects additions, removals, and order changes", () => {
  const first = createDocument();
  const second = createDocument({ id: "document-2", name: "second.txt" });

  assert.equal(areDocumentsEqual([first], [first, second]), false);
  assert.equal(areDocumentsEqual([first, second], [first]), false);
  assert.equal(areDocumentsEqual([first, second], [second, first]), false);
});
