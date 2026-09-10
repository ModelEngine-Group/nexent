import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const componentPath = new URL(
  "../app/[locale]/agents/components/collaborative-agent.tsx",
  import.meta.url
);

test("renders an internal agent version name as a muted V-prefixed label", async () => {
  const component = await readFile(componentPath, "utf8");

  assert.match(component, /versionName\?: string;/);
  assert.match(component, /V\{agent\.versionName\}/);
  assert.match(component, /versionName: agent\.version_name/);
});
