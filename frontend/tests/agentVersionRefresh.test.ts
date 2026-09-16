import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pagePath = new URL("../app/[locale]/agents/page.tsx", import.meta.url);
const versionPanelPath = new URL("../app/[locale]/agents/agent-version.tsx", import.meta.url);
const versionCardPath = new URL(
  "../app/[locale]/agents/versions/agent-version-card.tsx",
  import.meta.url
);

test("shares refreshed current version state with the version management panel", async () => {
  const [page, versionPanel, versionCard] = await Promise.all([
    readFile(pagePath, "utf8"),
    readFile(versionPanelPath, "utf8"),
    readFile(versionCardPath, "utf8"),
  ]);

  assert.match(
    page,
    /<AgentVersion\s+currentVersionNo=\{agentInfo\?\.current_version_no\}\s+onRefreshAgentInfo=\{refetchAgentInfo\}/
  );
  assert.match(versionPanel, /currentVersionNo\?: number/);
  assert.match(versionPanel, /onRefreshAgentInfo: \(\) => Promise<Agent \| null>/);
  assert.match(versionPanel, /currentVersionNo=\{currentVersionNo\}/);
  assert.match(versionPanel, /onRefreshAgentInfo=\{onRefreshAgentInfo\}/);
  assert.match(versionCard, /await onRefreshAgentInfo\?\.\(\)/);
});
