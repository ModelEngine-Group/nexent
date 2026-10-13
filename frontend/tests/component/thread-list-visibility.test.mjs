import assert from "node:assert/strict";
import { test } from "node:test";
import { getVisibleAgentThreads } from "../../app/[locale]/newchat/assistant-ui/thread-list-visibility.ts";

const entries = [
  { id: "newest", hasRemoteId: true, isRunning: false },
  { id: "older", hasRemoteId: true, isRunning: false },
];

test("collapsed inactive agents hide every conversation", () => {
  assert.deepEqual(getVisibleAgentThreads(entries, false, "another-agent"), []);
  assert.deepEqual(getVisibleAgentThreads(entries, false), []);
});

test("collapsed active agents show the open conversation rather than the newest", () => {
  assert.deepEqual(getVisibleAgentThreads(entries, false, "older"), [
    entries[1],
  ]);
});

test("expanded agents show all conversations whether active or inactive", () => {
  assert.deepEqual(
    getVisibleAgentThreads(entries, true, "another-agent"),
    entries
  );
  assert.deepEqual(getVisibleAgentThreads(entries, true, "older"), entries);
});

test("only the active conversation remains visible after switching agents", () => {
  assert.deepEqual(getVisibleAgentThreads(entries, false, "newest"), [
    entries[0],
  ]);
  assert.deepEqual(getVisibleAgentThreads(entries, false, "another-agent"), []);
});

test("unsent drafts stay hidden while running or titled active threads remain visible", () => {
  const draft = { id: "draft", hasRemoteId: false, isRunning: false };
  assert.deepEqual(getVisibleAgentThreads([draft], false, "draft"), []);
  const running = { ...draft, isRunning: true };
  assert.deepEqual(getVisibleAgentThreads([running], false, "draft"), [
    running,
  ]);
  const titles = new Map([["draft", "Hello"]]);
  assert.deepEqual(getVisibleAgentThreads([draft], false, "draft", titles), [
    draft,
  ]);
  assert.deepEqual(
    getVisibleAgentThreads([running], false, undefined, titles),
    []
  );
});
