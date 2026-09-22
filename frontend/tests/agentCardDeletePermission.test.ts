import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const actionsPath = new URL(
  "../app/[locale]/agents/components/agent-config-actions.tsx",
  import.meta.url
);
const pagePath = new URL("../app/[locale]/agents/page.tsx", import.meta.url);

test("uses each agent card permission for its delete action", async () => {
  const [actions, page] = await Promise.all([
    readFile(actionsPath, "utf8"),
    readFile(pagePath, "utf8"),
  ]);

  assert.match(actions, /readOnly\?: boolean/);
  assert.match(actions, /const isReadOnly = readOnly \?\? storeIsReadOnly;/);
  assert.match(
    page,
    /<AgentConfigActions\s+agentId=\{Number\(agent\.id\)\}\s+readOnly=\{agent\.permission === "READ_ONLY"\}\s+variant="menu"/
  );
});
