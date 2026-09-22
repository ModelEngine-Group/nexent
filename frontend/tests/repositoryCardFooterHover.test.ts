import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const footerButtonClass =
  "!text-slate-600 hover:!bg-transparent hover:!text-blue-500";

const footerButtonSources = new Map([
  ["app/[locale]/agent-space/agent-space.tsx", 1],
  ["app/[locale]/mcp-space/components/MineMcpServiceCard.tsx", 1],
  ["app/[locale]/mcp-space/components/RepositoryMcpCard.tsx", 0],
  ["app/[locale]/skill-space/components/MineSkillsView.tsx", 3],
  ["app/[locale]/skill-space/components/RepositoryView.tsx", 1],
]);

test("keeps repository card footer text buttons transparent and blue on hover", () => {
  for (const [sourcePath, expectedButtonCount] of footerButtonSources) {
    const source = readFileSync(`./${sourcePath}`, "utf8");
    const footerButtonMatches = source.match(
      new RegExp(`className=["']${footerButtonClass}["']`, "g")
    );

    assert.equal(
      footerButtonMatches?.length ?? 0,
      expectedButtonCount,
      `${sourcePath} styles every interactive card footer button`
    );
  }
});

test("does not apply hover styling to an installed MCP card action", () => {
  const source = readFileSync(
    "./app/[locale]/mcp-space/components/RepositoryMcpCard.tsx",
    "utf8"
  );

  assert.match(
    source,
    new RegExp(
      `className=\\{\\s*installed\\s*\\? undefined\\s*:\\s*["']${footerButtonClass}["']\\s*\\}`
    )
  );
});
