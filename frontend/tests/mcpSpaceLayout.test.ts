import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const route = new URL("../app/[locale]/mcp-space/", import.meta.url);
const agentPage = new URL(
  "../app/[locale]/agent-space/page.tsx",
  import.meta.url
);

test("MCP space delegates each tab to a separate component", async () => {
  const page = await readFile(new URL("page.tsx", route), "utf8");
  for (const component of [
    "McpRepository",
    "MyMcpServices",
    "McpReviewCenter",
  ]) {
    assert.match(page, new RegExp(`<${component}\\b`));
    assert.doesNotMatch(page, new RegExp(`function ${component}\\b`));
  }
  assert.doesNotMatch(
    page,
    /function (RepositoryView|MineView|ReviewCenterView)\b/
  );
});

test("MCP space matches agent space horizontal spacing and tabs", async () => {
  const [page, agent] = await Promise.all([
    readFile(new URL("page.tsx", route), "utf8"),
    readFile(agentPage, "utf8"),
  ]);
  const spacing = /px-4 py-8 sm:px-6 sm:py-10 xl:px-16/;
  const tabs = /justify-start[^\"]*border-b[^\"]*bg-transparent/;
  assert.match(agent, spacing);
  assert.match(page, spacing);
  assert.match(agent, tabs);
  assert.match(page, tabs);
  assert.doesNotMatch(page, /max-w-6xl/);
  assert.match(page, /data-\[state=active\]:border-primary/);
});
