import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const cardPath = new URL(
  "../app/[locale]/agent-space/components/MyAgentCard.tsx",
  import.meta.url
);

test("my agent lifecycle badge aligns with the top-right more menu", async () => {
  const card = await readFile(cardPath, "utf8");

  assert.match(
    card,
    /<div className="flex shrink-0 items-center gap-1\.5">[\s\S]*agentRepository\.mine\.lifecycle\.published[\s\S]*<Dropdown/
  );
});
