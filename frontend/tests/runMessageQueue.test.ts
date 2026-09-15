import assert from "node:assert/strict";
import test from "node:test";
import {
  EMPTY_RUN_MESSAGE,
  canAutoSendQueuedMessage,
  reduceRunMessage,
  type QueuedRunMessage,
  // @ts-expect-error -- Node's built-in TypeScript runner needs the extension.
} from "../features/humanInteraction/runMessageQueue.ts";

const entry = (): QueuedRunMessage => ({
  id: "message-1",
  text: "Keep it brief",
  runId: "run-1",
  previousRunId: null,
  durable: true,
  status: "queued",
});
const initial = () =>
  reduceRunMessage(EMPTY_RUN_MESSAGE, { type: "enqueue", entry: entry() });

test("one outstanding message blocks another until delivery, including after deletion", () => {
  const state = initial();
  assert.equal(
    reduceRunMessage(state, {
      type: "enqueue",
      entry: { ...entry(), id: "second" },
    }),
    state
  );
  const deleted = reduceRunMessage(state, { type: "delete" });
  assert.equal(deleted.entry, null);
  assert.equal(
    reduceRunMessage(deleted, { type: "enqueue", entry: entry() }),
    deleted
  );
  assert.deepEqual(
    reduceRunMessage(deleted, { type: "idle" }),
    EMPTY_RUN_MESSAGE
  );
});

test("editing retains identity and blocks auto dispatch until saved", () => {
  const editing = reduceRunMessage(initial(), { type: "edit" });
  assert.equal(
    canAutoSendQueuedMessage(
      editing.entry,
      { run_id: "run-1", status: "COMPLETED" },
      false,
      true
    ),
    false
  );
  const saved = reduceRunMessage(editing, {
    type: "save",
    text: "New direction",
  });
  assert.equal(saved.entry?.id, "message-1");
  assert.equal(saved.entry?.text, "New direction");
  assert.equal(saved.entry?.status, "queued");
});

test("accepted guidance releases the composer for successive guidance in the same run", () => {
  const delivering = reduceRunMessage(initial(), { type: "deliver" });
  assert.equal(reduceRunMessage(delivering, { type: "delete" }), delivering);
  const guided = reduceRunMessage(delivering, {
    type: "guided",
    messageId: "message-1",
  });
  assert.deepEqual(guided, EMPTY_RUN_MESSAGE);
  assert.equal(reduceRunMessage(guided, { type: "edit" }), guided);
  assert.equal(reduceRunMessage(guided, { type: "delete" }), guided);
  assert.equal(
    canAutoSendQueuedMessage(
      guided.entry,
      { run_id: "run-1", status: "COMPLETED" },
      false,
      true
    ),
    false
  );
  const next = reduceRunMessage(guided, {
    type: "enqueue",
    entry: { ...entry(), id: "message-2", text: "Use bullet points" },
  });
  assert.equal(next.entry?.runId, "run-1");
  assert.equal(next.entry?.id, "message-2");
  assert.deepEqual(
    reduceRunMessage(reduceRunMessage(next, { type: "deliver" }), {
      type: "guided",
      messageId: "message-2",
    }),
    EMPTY_RUN_MESSAGE
  );
});

test("the next queued message still auto-sends after an earlier message guided the run", () => {
  const guided = reduceRunMessage(
    reduceRunMessage(initial(), { type: "deliver" }),
    {
      type: "guided",
      messageId: "message-1",
    }
  );
  const queued = reduceRunMessage(guided, {
    type: "enqueue",
    entry: { ...entry(), id: "next-turn", text: "Summarize the result" },
  });
  assert.equal(
    canAutoSendQueuedMessage(
      queued.entry,
      { run_id: "run-1", status: "RUNNING" },
      true,
      false
    ),
    false
  );
  assert.equal(
    canAutoSendQueuedMessage(
      queued.entry,
      { run_id: "run-1", status: "COMPLETED" },
      false,
      true
    ),
    true
  );
  assert.deepEqual(
    reduceRunMessage(reduceRunMessage(queued, { type: "deliver" }), {
      type: "sent",
    }),
    EMPTY_RUN_MESSAGE
  );
});

test("late acknowledgments and failures cannot modify the next message", () => {
  const guided = reduceRunMessage(
    reduceRunMessage(initial(), { type: "deliver" }),
    {
      type: "guided",
      messageId: "message-1",
    }
  );
  const next = reduceRunMessage(
    reduceRunMessage(guided, {
      type: "enqueue",
      entry: { ...entry(), id: "message-2" },
    }),
    { type: "deliver" }
  );
  assert.equal(
    reduceRunMessage(next, { type: "guided", messageId: "message-1" }),
    next
  );
  assert.equal(
    reduceRunMessage(next, {
      type: "error",
      messageId: "message-1",
      error: "Old response failed",
      uncertain: true,
    }),
    next
  );
});

test("only matching completed loop plus drained stream sends the next turn", () => {
  for (const status of [
    "READY",
    "RUNNING",
    "WAITING_HUMAN",
    "FAILED",
    "STOPPED",
    "EXPIRED",
    "RECOVERY_REQUIRED",
  ]) {
    assert.equal(
      canAutoSendQueuedMessage(
        entry(),
        { run_id: "run-1", status },
        false,
        true
      ),
      false
    );
  }
  assert.equal(
    canAutoSendQueuedMessage(
      entry(),
      { run_id: "other-run", status: "COMPLETED" },
      false,
      true
    ),
    false
  );
  assert.equal(
    canAutoSendQueuedMessage(
      entry(),
      { run_id: "run-1", status: "COMPLETED" },
      true,
      true
    ),
    false
  );
  assert.equal(
    canAutoSendQueuedMessage(
      entry(),
      { run_id: "run-1", status: "COMPLETED" },
      false,
      true
    ),
    true
  );
});

test("connecting state never binds a queue to the previous finished run", () => {
  const state = {
    used: true,
    entry: { ...entry(), runId: null, previousRunId: "previous" },
  };
  assert.equal(
    reduceRunMessage(state, { type: "bind", runId: "previous" }),
    state
  );
  assert.equal(
    reduceRunMessage(state, { type: "bind", runId: "new-run" }).entry?.runId,
    "new-run"
  );
});

test("failed guide keeps text and idempotency identity, but does not auto send", () => {
  const failed = reduceRunMessage(
    reduceRunMessage(initial(), { type: "deliver" }),
    { type: "error", error: "Network" }
  );
  assert.equal(failed.entry?.id, "message-1");
  assert.equal(failed.entry?.text, "Keep it brief");
  assert.equal(
    canAutoSendQueuedMessage(
      failed.entry,
      { run_id: "run-1", status: "COMPLETED" },
      false,
      true
    ),
    false
  );
});

test("an uncertain guide cannot be edited or dispatched again as a new turn", () => {
  const uncertain = reduceRunMessage(
    reduceRunMessage(initial(), { type: "deliver" }),
    {
      type: "error",
      error: "Response lost",
      uncertain: true,
    }
  );
  assert.equal(reduceRunMessage(uncertain, { type: "edit" }), uncertain);
  assert.equal(reduceRunMessage(uncertain, { type: "delete" }), uncertain);
  assert.equal(
    canAutoSendQueuedMessage(
      uncertain.entry,
      { run_id: "run-1", status: "COMPLETED" },
      false,
      true
    ),
    false
  );
  assert.equal(
    reduceRunMessage(uncertain, { type: "deliver" }).entry?.id,
    "message-1"
  );
});
