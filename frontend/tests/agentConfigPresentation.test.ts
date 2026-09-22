import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pagePath = new URL("../app/[locale]/agents/page.tsx", import.meta.url);
const agentsPath = new URL(
  "../app/[locale]/agents/agents.tsx",
  import.meta.url
);
const versionCardPath = new URL(
  "../app/[locale]/agents/versions/agent-version-card.tsx",
  import.meta.url
);

test("keeps the agent configuration workspace white", async () => {
  const [page, agents] = await Promise.all([
    readFile(pagePath, "utf8"),
    readFile(agentsPath, "utf8"),
  ]);

  assert.match(page, /<div className="flex h-full min-h-0 flex-col bg-white">/);
  assert.match(
    page,
    /<div className="flex h-full min-h-0 flex-col overflow-hidden bg-white px-4 py-6 sm:px-6 xl:px-16">/
  );
  assert.match(
    agents,
    /<div className="flex h-full w-full min-h-0 flex-col bg-white">/
  );
});

test("only marks a positive published version as current", async () => {
  const versionCard = await readFile(versionCardPath, "utf8");

  assert.match(
    versionCard,
    /const isCurrentVersion =\s*typeof currentVersionNo === "number"\s*&&\s*currentVersionNo > 0\s*&&\s*currentVersionNo === version\.version_no;/
  );
});
