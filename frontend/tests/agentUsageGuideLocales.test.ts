import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const localeRoot = new URL("../public/locales/", import.meta.url);

function loadLocale(locale: "en" | "zh"): Record<string, string> {
  return JSON.parse(
    readFileSync(new URL(`${locale}/common.json`, localeRoot), "utf8")
  ) as Record<string, string>;
}

test("keeps Agent usage guide locale keys aligned and complete", () => {
  const english = loadLocale("en");
  const chinese = loadLocale("zh");
  const prefix = /^agentUsageGuide\./;
  const englishKeys = Object.keys(english)
    .filter((key) => prefix.test(key))
    .sort();
  const chineseKeys = Object.keys(chinese)
    .filter((key) => prefix.test(key))
    .sort();

  assert.deepEqual(chineseKeys, englishKeys);
});
