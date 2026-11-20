// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import assert from "node:assert/strict";
import test from "node:test";

import i18next from "i18next";
import en from "../public/locales/en/common.json" with { type: "json" };
import zh from "../public/locales/zh/common.json" with { type: "json" };

await i18next.init({
  lng: "en",
  fallbackLng: "en",
  defaultNS: "common",
  resources: { en: { common: en } },
});

for (const [key, singular, plural] of [
  ["systemConfig.paramCount", "1 setting", "2 settings"],
  [
    "systemConfig.save.description",
    "The following 1 setting will be saved to PostgreSQL. Consumers will refresh automatically.",
    "The following 2 settings will be saved to PostgreSQL. Consumers will refresh automatically.",
  ],
  [
    "systemConfig.save.success",
    "Saved 1 setting. Consumers will refresh automatically.",
    "Saved 2 settings. Consumers will refresh automatically.",
  ],
  ["systemConfig.saveBar.count", "1 unsaved change", "2 unsaved changes"],
]) {
  test(`${key} uses correct English singular and plural forms`, () => {
    assert.equal(i18next.t(key, { count: 1 }), singular);
    assert.equal(i18next.t(key, { count: 2 }), plural);
  });
}

test("English and Chinese system-configuration keys stay aligned", () => {
  const englishKeys = Object.keys(en).filter((key) =>
    key.startsWith("systemConfig.")
  );
  const chineseKeys = Object.keys(zh).filter((key) =>
    key.startsWith("systemConfig.")
  );
  assert.deepEqual(englishKeys.sort(), chineseKeys.sort());
});
