import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const componentPath = new URL(
  "../app/[locale]/agents/components/collaborative-agent.tsx",
  import.meta.url
);
const selectorPath = new URL(
  "../app/[locale]/agents/components/advanced/collaborative-agent-selector-modal.tsx",
  import.meta.url
);

test("renders an internal agent version number as a muted label", async () => {
  const component = await readFile(componentPath, "utf8");

  assert.match(component, /versionNo\?: number;/);
  assert.match(component, /V\{agent\.versionNo\}/);
  assert.match(component, /versionNo: agent\.version_no/);
  assert.doesNotMatch(component, /versionName: agent\.version_name/);
});

test("shows both version number and version name while selecting an internal agent", async () => {
  const selector = await readFile(selectorPath, "utf8");

  assert.match(selector, /current_version_no/);
  assert.match(selector, /version_name/);
  assert.match(selector, /V\$\{internalAgent\.current_version_no\}/);
});
