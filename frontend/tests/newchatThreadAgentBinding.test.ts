import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pagePath = new URL("../app/[locale]/newchat/page.tsx", import.meta.url);

test("binds an agent selected for a new thread to that thread's metadata", async () => {
  const page = await readFile(pagePath, "utf8");

  assert.match(
    page,
    /getItemById\(runtime\.threads\.getState\(\)\.mainThreadId\)\s*\.updateCustom\(\{[\s\S]*agentId:\s*agent\.id\s*\}\)/
  );
});
