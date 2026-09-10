import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const selectorPath = new URL(
  "../app/[locale]/agents/agent-selector-header.tsx",
  import.meta.url
);

test("loads and initializes the selected agent before changing its URL", async () => {
  const selector = await readFile(selectorPath, "utf8");
  const initializeIndex = selector.indexOf("initialize(result.data);");
  const replaceIndex = selector.indexOf(
    "router.replace(`${pathname}?${nextSearchParams.toString()}`);"
  );

  assert.notEqual(initializeIndex, -1);
  assert.notEqual(replaceIndex, -1);
  assert.ok(
    initializeIndex < replaceIndex,
    "selector must initialize the selected agent before updating the URL"
  );
});
