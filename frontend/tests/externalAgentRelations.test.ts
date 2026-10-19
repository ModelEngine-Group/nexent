// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import assert from "node:assert/strict";
import test from "node:test";
import { synchronizeExternalAgentRelations } from "../lib/externalAgentRelations";

function fixture(
  failAdd: number[] = [],
  throwAdd: number[] = [],
  failRemove: number[] = []
) {
  const calls: string[] = [];
  return {
    calls,
    client: {
      addRelation: async (agent: number, id: number) => {
        calls.push(`add:${agent}:${id}`);
        if (throwAdd.includes(id)) throw new Error("network");
        return { success: !failAdd.includes(id) };
      },
      removeRelation: async (agent: number, id: number) => {
        calls.push(`remove:${agent}:${id}`);
        return { success: !failRemove.includes(id) };
      },
    },
  };
}

test("synchronizes only changed relations and does not mutate input arrays", async () => {
  const f = fixture();
  const current = [10, 20],
    target = [20, 30];
  const result = await synchronizeExternalAgentRelations(
    1,
    current,
    target,
    f.client
  );
  assert.deepEqual(f.calls, ["add:1:30", "remove:1:10"]);
  assert.deepEqual(result, {
    synchronizedIds: [20, 30],
    succeeded: 2,
    failed: 0,
  });
  assert.deepEqual(current, [10, 20]);
  assert.deepEqual(target, [20, 30]);
});
test("unchanged selections make no relation requests", async () => {
  const f = fixture();
  assert.deepEqual(
    await synchronizeExternalAgentRelations(1, [20], [20], f.client),
    { synchronizedIds: [20], succeeded: 0, failed: 0 }
  );
  assert.deepEqual(f.calls, []);
});
test("records partial success from returned failure and rejection", async () => {
  const f = fixture([30], [40]);
  const result = await synchronizeExternalAgentRelations(
    1,
    [10],
    [20, 30, 40],
    f.client
  );
  assert.deepEqual(result, { synchronizedIds: [20], succeeded: 2, failed: 2 });
});
test("retry or reopen uses confirmed ids and never repeats successful operations", async () => {
  const first = fixture([30], [40]);
  const partial = await synchronizeExternalAgentRelations(
    1,
    [10],
    [20, 30, 40],
    first.client
  );
  const retry = fixture();
  const result = await synchronizeExternalAgentRelations(
    1,
    partial.synchronizedIds,
    [20, 30, 40],
    retry.client
  );
  assert.deepEqual(retry.calls, ["add:1:30", "add:1:40"]);
  assert.deepEqual(result, {
    synchronizedIds: [20, 30, 40],
    succeeded: 2,
    failed: 0,
  });
});
test("failed removals remain in confirmed state and are retried", async () => {
  const first = fixture([], [], [10]);
  const partial = await synchronizeExternalAgentRelations(
    1,
    [10, 20],
    [30],
    first.client
  );
  assert.deepEqual(partial, {
    synchronizedIds: [10, 30],
    succeeded: 2,
    failed: 1,
  });
  const retry = fixture();
  await synchronizeExternalAgentRelations(
    1,
    partial.synchronizedIds,
    [30],
    retry.client
  );
  assert.deepEqual(retry.calls, ["remove:1:10"]);
});
test("waits for slow successes after a sibling rejection", async () => {
  let resolve!: (value: { success: boolean }) => void;
  let finished = false;
  const request = synchronizeExternalAgentRelations(1, [], [20, 30], {
    addRelation: async (_agent: number, id: number) => {
      if (id === 20) throw new Error("network");
      return new Promise<{ success: boolean }>((done) => {
        resolve = done;
      });
    },
    removeRelation: async () => ({ success: true }),
  }).then((result) => {
    finished = true;
    return result;
  });
  await Promise.resolve();
  assert.equal(finished, false);
  resolve({ success: true });
  assert.deepEqual(await request, {
    synchronizedIds: [30],
    succeeded: 1,
    failed: 1,
  });
});
test("changing the draft after partial success computes inverse operations correctly", async () => {
  const first = fixture([30]);
  const partial = await synchronizeExternalAgentRelations(
    1,
    [10],
    [20, 30],
    first.client
  );
  const changed = fixture();
  await synchronizeExternalAgentRelations(
    1,
    partial.synchronizedIds,
    [10],
    changed.client
  );
  assert.deepEqual(changed.calls, ["add:1:10", "remove:1:20"]);
});
test("deduplicates ids and keeps the confirmed state on total failure", async () => {
  const f = fixture([20], [], [10]);
  assert.deepEqual(
    await synchronizeExternalAgentRelations(1, [10, 10], [20, 20], f.client),
    { synchronizedIds: [10], succeeded: 0, failed: 2 }
  );
  assert.deepEqual(f.calls, ["add:1:20", "remove:1:10"]);
});
