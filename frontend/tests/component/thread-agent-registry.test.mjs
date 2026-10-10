import assert from "node:assert/strict";
import { test } from "node:test";
import {
  resolveThreadAgentId,
  startAgentConversation,
} from "../../app/[locale]/newchat/adapter/thread-agent-registry.ts";

test("agent metadata accepts numeric and string IDs before the local fallback", () => {
  assert.equal(resolveThreadAgentId(7, 8), 7);
  assert.equal(resolveThreadAgentId("7", 8), 7);
  for (const value of [undefined, null, "", "unknown", 0, -1, 1.5, true]) {
    assert.equal(resolveThreadAgentId(value, 8), 8);
    assert.equal(resolveThreadAgentId(value), null);
  }
});

test("starting a conversation keeps the initialized thread bound to its agent", async () => {
  let mainThreadId = "existing-thread";
  let draftId;
  let switches = 0;
  const items = new Map();
  const runtime = {
    threads: {
      async switchToNewThread() {
        switches += 1;
        if (!draftId) {
          draftId = `new-thread-${switches}`;
          const id = draftId;
          items.set(id, {
            custom: undefined,
            async initialize() {
              // Initialization consumes the draft, so another switch would
              // create a different thread without the selected agent.
              draftId = undefined;
            },
            async updateCustom(custom) {
              items.get(id).custom = custom;
            },
          });
        }
        mainThreadId = draftId;
      },
      getState: () => ({ mainThreadId }),
      getItemById: (id) => items.get(id),
    },
  };

  await startAgentConversation(runtime, 7);
  assert.equal(switches, 1);
  assert.equal(mainThreadId, "new-thread-1");
  assert.deepEqual(items.get(mainThreadId).custom, { agentId: 7 });

  await startAgentConversation(runtime, 8);
  assert.equal(switches, 2);
  assert.equal(mainThreadId, "new-thread-2");
  assert.deepEqual(items.get(mainThreadId).custom, { agentId: 8 });
  assert.deepEqual(items.get("new-thread-1").custom, { agentId: 7 });
});

test("invalid agents do not switch or initialize a conversation", async () => {
  const runtime = {
    threads: {
      switchToNewThread: () =>
        assert.fail("Must not switch for an invalid agent"),
    },
  };
  for (const agentId of [0, -1, NaN, 1.5]) {
    await assert.rejects(
      startAgentConversation(runtime, agentId),
      /valid agent ID/
    );
  }
});
