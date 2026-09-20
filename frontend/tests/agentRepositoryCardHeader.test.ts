import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const spacePath = new URL(
  "../app/[locale]/agent-space/space.tsx",
  import.meta.url
);

test("repository card keeps downloads in the top-right action area", async () => {
  const space = await readFile(spacePath, "utf8");

  assert.match(
    space,
    /headerActions=\{[\s\S]*<Download[\s\S]*downloads\.toLocaleString\(\)[\s\S]*showAdminMenu[\s\S]*<Dropdown/
  );
});
