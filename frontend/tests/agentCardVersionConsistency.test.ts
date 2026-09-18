import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const repositoryCardPath = new URL(
  "../app/[locale]/agent-space/space.tsx",
  import.meta.url
);

test("repository cards use the same current-version treatment as my agent cards", async () => {
  const repositoryCard = await readFile(repositoryCardPath, "utf8");

  assert.match(
    repositoryCard,
    /badge=\{[\s\S]*text-\[11px\][\s\S]*bg-primary[\s\S]*agentRepository\.mine\.currentVersion/
  );
  assert.doesNotMatch(
    repositoryCard,
    /rounded-md bg-primary\/10 px-2 py-0\.5 text-xs font-medium text-primary/
  );
});
