import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pagePath = new URL("../app/[locale]/agents/page.tsx", import.meta.url);
const editorPagePath = new URL(
  "../app/[locale]/agents/agent-editor-page.tsx",
  import.meta.url
);
const agentsPath = new URL(
  "../app/[locale]/agents/agents.tsx",
  import.meta.url
);
test("keeps the agent configuration workspace white", async () => {
  const [page, editorPage, agents] = await Promise.all([
    readFile(pagePath, "utf8"),
    readFile(editorPagePath, "utf8"),
    readFile(agentsPath, "utf8"),
  ]);

  assert.match(
    editorPage,
    /<div className="flex h-full min-h-0 flex-col bg-white">/
  );
  assert.match(
    page,
    /<div className="flex h-full min-h-0 flex-col overflow-hidden bg-white px-4 py-6 sm:px-6 xl:px-16">/
  );
  assert.match(
    agents,
    /<div className="flex h-full w-full min-h-0 flex-col bg-white">/
  );
  assert.match(
    page,
    /subtitle=\{\s*agent\.current_version_no\s*\?\s*t\("agentRepository\.mine\.currentVersion",/
  );
  assert.match(
    page,
    /className="!text-slate-600 hover:!bg-transparent hover:!text-blue-500"/
  );
});

test("reinitializes NL2Agent for the loaded Agent without an unavailable banner", async () => {
  const agents = await readFile(agentsPath, "utf8");

  assert.match(
    agents,
    /key=\{`\$\{currentAgentId \?\? "unselected"\}-\$\{sessionGeneration\}`\}/
  );
  assert.doesNotMatch(agents, /nl2agent\.unavailable/);
});
