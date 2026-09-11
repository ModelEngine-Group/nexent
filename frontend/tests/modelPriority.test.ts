import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const modelPriorityPath = "../lib/agent/modelPriority.ts";
const agentPromptPath = new URL(
  "../app/[locale]/agents/components/agent-prompt.tsx",
  import.meta.url
);

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

test("shows model priority sorting only from a popover trigger", async () => {
  const prompt = await readFile(agentPromptPath, "utf8");

  assert.match(prompt, /import \{[\s\S]*Popover[\s\S]*\} from "antd"/);
  assert.match(
    prompt,
    /const \[isModelPriorityOpen, setIsModelPriorityOpen\] = useState\(false\)/
  );
  assert.match(prompt, /<Popover[\s\S]*open=\{isModelPriorityOpen\}/);
  assert.match(prompt, /icon=\{<ListOrdered/);
  assert.match(prompt, /content=\{modelPriorityContent\}/);
});
