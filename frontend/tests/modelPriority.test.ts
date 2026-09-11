import assert from "node:assert/strict";
import test from "node:test";

const modelPriorityPath = "../lib/agent/modelPriority.ts";

const models = [
  { value: 1, displayName: "Primary" },
  { value: 2, displayName: "Fallback A" },
  { value: 3, displayName: "Fallback B" },
];

test("moves a model into the primary position and keeps names in priority order", async () => {
  const { reorderModelIds, resolveModelSelection } = await import(
    modelPriorityPath
  );
  const modelIds = reorderModelIds([1, 2, 3], 3, 1);

  assert.deepEqual(modelIds, [3, 1, 2]);
  assert.deepEqual(resolveModelSelection(modelIds, models), {
    model: "Fallback B",
    model_ids: [3, 1, 2],
    model_names: ["Fallback B", "Primary", "Fallback A"],
  });
});
