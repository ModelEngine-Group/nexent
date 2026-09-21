import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

const route = new URL("../app/[locale]/mcp-space/", import.meta.url);
const agentPage = new URL(
  "../app/[locale]/agent-space/page.tsx",
  import.meta.url
);
const mcpSpacePath = new URL(
  "../app/[locale]/mcp-space/agent-space.tsx",
  import.meta.url
);
const myMcpPath = new URL(
  "../app/[locale]/mcp-space/my-mcp.tsx",
  import.meta.url
);
const mineMcpCardPath = new URL(
  "../app/[locale]/mcp-space/components/MineMcpServiceCard.tsx",
  import.meta.url
);

test("MCP space delegates each tab to a separate component", async () => {
  const page = await readFile(new URL("page.tsx", route), "utf8");
  for (const component of ["McpSpace", "MyMcp", "ReviewCenter"]) {
    assert.match(page, new RegExp(`<${component}\\b`));
    assert.doesNotMatch(page, new RegExp(`function ${component}\\b`));
  }
  const files = await readdir(route);
  for (const name of ["agent-space.tsx", "my-mcp.tsx", "review-center.tsx"]) {
    assert.ok(files.includes(name), `${name} is a separate tab component`);
  }
  for (const name of [
    "repository.tsx",
    "my-mcp-services.tsx",
    "mcp-space-shared.tsx",
    "use-mcp-space-controller.tsx",
  ]) {
    assert.ok(!files.includes(name), `${name} is no longer needed`);
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

test("MCP repository grid uses the agent repository responsive capacity", async () => {
  const page = await readFile(mcpSpacePath, "utf8");

  assert.match(page, /Grid\.useBreakpoint\(\)/);
  assert.match(page, /const pageSize = columns \* rows;/);
  assert.match(page, /onPageSizeChange\(pageSize\)/);
  assert.match(page, /const gridHeight =/);
  assert.match(page, /browser\.total > 0 \? PAGINATION_HEIGHT : 0/);
  assert.match(
    page,
    /<ResourceCardGrid[\s\S]*page=\{browser\.page\}[\s\S]*total=\{browser\.total\}[\s\S]*onPageChange=\{browser\.setPage\}[\s\S]*columns=\{columns\}[\s\S]*rows=\{rows\}[\s\S]*gridHeight=\{gridHeight\}/
  );
  assert.match(page, /useMcpCommunityBrowser\([\s\S]*repositoryPageSize/);
  assert.match(page, /onPageSizeChange: setRepositoryPageSize/);
  assert.doesNotMatch(page, /<McpToolsPagination/);
});

test("my MCP grid uses the agent repository responsive capacity", async () => {
  const page = await readFile(myMcpPath, "utf8");

  assert.match(page, /Grid\.useBreakpoint\(\)/);
  assert.match(page, /const pageSize = columns \* rows;/);
  assert.match(page, /const itemsPerPage = Math\.max\(1, pageSize - 1\);/);
  assert.match(page, /const gridHeight =/);
  assert.match(page, /filteredItems\.length > 0 \? PAGINATION_HEIGHT : 0/);
  assert.match(
    page,
    /<ResourceCardGrid[\s\S]*page=\{page\}[\s\S]*total=\{filteredItems\.length\}[\s\S]*onPageChange=\{setPage\}[\s\S]*columns=\{columns\}[\s\S]*rows=\{rows\}[\s\S]*gridHeight=\{gridHeight\}/
  );
  assert.doesNotMatch(page, /<ResponsiveCardGrid/);
});

test("my MCP cards open on click and retain only the enabled action", async () => {
  const [page, card] = await Promise.all([
    readFile(myMcpPath, "utf8"),
    readFile(mineMcpCardPath, "utf8"),
  ]);

  assert.match(card, /<ResourceCard[\s\S]*onClick=\{handleEdit\}/);
  assert.match(card, /footerLayout="inline"/);
  assert.match(card, /meta=\{[\s\S]*createDate/);
  assert.match(card, /headerActions=\{/);
  assert.match(card, /flex flex-col items-start gap-1/);
  assert.match(
    card,
    /className="h-8 px-3 text-xs font-medium text-primary !shadow-none hover:!bg-transparent hover:!text-primary\/80"/
  );
  assert.doesNotMatch(card, /Edit3|Share2|mcpTools\.mine\.onHub/);
  assert.match(page, /searchActions=\{/);
  assert.doesNotMatch(page, /filterActions=\{/);
});

test("my MCP header actions keep the more menu beside refresh", async () => {
  const card = await readFile(mineMcpCardPath, "utf8");

  assert.match(
    card,
    /flex flex-col items-start gap-1[\s\S]*flex items-center gap-1[\s\S]*RefreshCw[\s\S]*MoreHorizontal[\s\S]*reviewBadge[\s\S]*self-end/
  );
});
