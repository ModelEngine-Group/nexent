import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const selectorPath = new URL(
  "../app/[locale]/agents/components/advanced/collaborative-agent-selector-modal.tsx",
  import.meta.url
);
const zhLocalePath = new URL(
  "../public/locales/zh/common.json",
  import.meta.url
);
const enLocalePath = new URL(
  "../public/locales/en/common.json",
  import.meta.url
);

test("labels the custom version name in the collaborative agent selector", async () => {
  const [selector, zhLocaleText, enLocaleText] = await Promise.all([
    readFile(selectorPath, "utf8"),
    readFile(zhLocalePath, "utf8"),
    readFile(enLocalePath, "utf8"),
  ]);
  const zhLocale = JSON.parse(zhLocaleText) as Record<string, string>;
  const enLocale = JSON.parse(enLocaleText) as Record<string, string>;

  assert.match(
    selector,
    /t\("agent\.collaborative\.selector\.versionName",\s*\{\s*name: internalAgent\.version_name,?\s*\}\s*\)/
  );
  assert.equal(
    zhLocale["agent.collaborative.selector.versionName"],
    "名称：{{name}}"
  );
  assert.equal(
    enLocale["agent.collaborative.selector.versionName"],
    "Name: {{name}}"
  );
});
