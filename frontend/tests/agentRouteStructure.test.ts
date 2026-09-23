import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

const agentsPagePath = "./app/[locale]/agents/page.tsx";
const editorPagePath = "./app/[locale]/agents/[agentId]/page.tsx";

test("keeps the agents index as a card list without an edit query branch", () => {
  const source = readFileSync(agentsPagePath, "utf8");

  assert.doesNotMatch(source, /\bisEditing\b/);
  assert.doesNotMatch(source, /agent_id/);
  assert.match(source, /router\.push\(`\$\{pathname\}\/\$\{agentId\}`\)/);
  assert.match(source, /onClick=\{\(\) => void handleOpenDetail\(agent\)\}/);
  assert.match(source, /onClick=\{\(\) => updateUrl\(Number\(agent\.id\)\)\}/);
});

test("provides a dedicated dynamic route for agent configuration", () => {
  assert.equal(existsSync(editorPagePath), true);
  assert.equal(existsSync("./app/[locale]/agents/[agentId]/agent-editor.tsx"), false);
  assert.equal(existsSync("./app/[locale]/agents/agent-editor-page.tsx"), false);

  const editor = readFileSync(editorPagePath, "utf8");
  assert.match(editor, /export default function AgentEditor\(\)/);
  assert.match(editor, /searchAgentInfo\(requestedAgentId\)/);
  assert.match(editor, /<Nl2AgentFlowProvider>\s*<AgentSetupContent \/>/);
});
