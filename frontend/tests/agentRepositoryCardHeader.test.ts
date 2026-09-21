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

test("repository card copy action uses a transparent text-button treatment", async () => {
  const space = await readFile(spacePath, "utf8");

  assert.match(
    space,
    /type="text"[\s\S]*className="h-8 px-3 text-xs font-medium text-primary !shadow-none hover:!bg-transparent hover:!text-primary\/80"[\s\S]*<Copy/
  );
  assert.doesNotMatch(space, /type="primary"[\s\S]*shadow-sm[\s\S]*<Copy/);
});
