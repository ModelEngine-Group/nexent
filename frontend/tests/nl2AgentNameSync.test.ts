import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const adapterPath = new URL(
  "../app/[locale]/newchat/adapter/remote-chat-model-adapter.ts",
  import.meta.url
);
const panelPath = new URL(
  "../app/[locale]/newchat/assistant-ui/nl2agent-chat-panel.tsx",
  import.meta.url
);
const flowPath = new URL("../contexts/nl2AgentFlow.tsx", import.meta.url);

test("accepts generated Agent names as draft-save state events", async () => {
  const adapter = await readFile(adapterPath, "utf8");

  assert.match(
    adapter,
    /export type Nl2AgentDraftField = "name" \| "description" \| Nl2aPromptField/
  );
  assert.match(
    adapter,
    /const draftFields = new Set<Nl2AgentDraftField>\(\[\s*"name",\s*"description"/
  );
});

test("locks the Agent form for the complete NL2Agent run lifecycle", async () => {
  const [panel, flow] = await Promise.all([
    readFile(panelPath, "utf8"),
    readFile(flowPath, "utf8"),
  ]);

  assert.match(panel, /onRunStart\?\.\(agentId\)/);
  assert.match(panel, /onRunEnd\?\.\(agentId\)/);
  assert.match(flow, /case "run_started"[\s\S]*?isFormLocked: true/);
  assert.match(flow, /case "run_finished"[\s\S]*?isFormLocked: false/);
});
