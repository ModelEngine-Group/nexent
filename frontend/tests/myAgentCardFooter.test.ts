import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const cardPath = new URL(
  "../app/[locale]/agent-space/components/MyAgentCard.tsx",
  import.meta.url
);

test("my agent card actions use the repository card text-button treatment", async () => {
  const card = await readFile(cardPath, "utf8");

  assert.match(
    card,
    /type="text"[\s\S]*className="h-8 px-3 text-xs font-medium text-primary !shadow-none hover:!bg-transparent hover:!text-primary\/80"/
  );
  assert.doesNotMatch(card, /type="default"/);
});
