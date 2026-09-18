import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const myAgentPath = new URL(
  "../app/[locale]/agent-space/my-agent.tsx",
  import.meta.url
);

test("my agent grid calculates and uses the available viewport height", async () => {
  const page = await readFile(myAgentPath, "utf8");

  assert.match(page, /Grid\.useBreakpoint\(\)/);
  assert.match(page, /const pageSize = columns \* rows;/);
  assert.match(page, /const gridHeight =/);
  assert.match(page, /<div ref=\{gridRegionRef\} className="min-h-0">/);
  assert.match(
    page,
    /<ResourceCardGrid[\s\S]*columns=\{columns\}[\s\S]*rows=\{rows\}[\s\S]*gridHeight=\{gridHeight\}/
  );
});
