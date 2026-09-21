import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const cardPath = new URL(
  "../app/[locale]/agent-space/components/MyAgentCard.tsx",
  import.meta.url
);

test("my agent repository status sits left of the lifecycle badge", async () => {
  const card = await readFile(cardPath, "utf8");

  assert.match(
    card,
    /<div className="flex shrink-0 flex-col items-end gap-1\.5">[\s\S]*<Dropdown[\s\S]*<div className="flex items-center gap-1\.5">[\s\S]*repositoryStatusBadge[\s\S]*agentRepository\.mine\.lifecycle\.published/
  );
});
