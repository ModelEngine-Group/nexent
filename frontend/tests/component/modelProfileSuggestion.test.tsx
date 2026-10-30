// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it } from "vitest";
import {
  suggestModelProfile,
  matchesProfileKeywords,
} from "../../app/[locale]/models/components/model/profileSuggestion";
import type { AtomicProfileSummary } from "../../types/modelProfile";
const profile = (key: string): AtomicProfileSummary => ({
  key,
  name: key,
  revision: "r1",
  catalog_kind: "model",
  qualification: "reference_only",
});
it("recognizes GLM version prefixes without confusing visual suffixes or minor versions", () => {
  const current = profile("zhipuai/glm-5.2");
  const profiles = [
    current,
    profile("zhipuai/glm-5"),
    profile("zhipuai/glm-5.3"),
  ];
  for (const id of ["GLM-V5.2", "zhipu/GLM-v5.2", "route-GLM-V5.2-online"])
    expect(suggestModelProfile(id, profiles)).toBe(current);
  expect(suggestModelProfile("GLM-V5.20", profiles)).toBeUndefined();
  expect(suggestModelProfile("GLM-4.6V", profiles)).toBeUndefined();
});
it("suggests the longest contained model name without crossing unrelated or ambiguous identities", () => {
  const qwen = profile("qwen3.5-plus");
  expect(suggestModelProfile("deploy-Qwen3.5-Plus-latest", [qwen])).toBe(qwen);
  expect(suggestModelProfile("deepseek-v4", [qwen])).toBeUndefined();
  expect(suggestModelProfile("", [qwen])).toBeUndefined();
  expect(
    suggestModelProfile("deploy-qwen3.5-plus", [
      qwen,
      profile("vendor/qwen3.5-plus"),
    ])
  ).toBeUndefined();
  expect(suggestModelProfile("qwen3.5-plus", [qwen, profile("qwen3.5")])).toBe(
    qwen
  );
});

it("suggests a stable same-version profile for a short model ID and searches normalized keywords", () => {
  const base = profile("alibaba/qwen3.8-27b");
  const max = profile("alibaba/qwen3.8-max");
  const older = profile("alibaba/qwen3.5-plus");
  expect(suggestModelProfile("Qwen3.8", [max, older, base])).toBe(base);
  expect(suggestModelProfile("qwen3.8-max", [base, max])).toBe(max);
  expect(suggestModelProfile("qwen3.9", [base, max])).toBeUndefined();
  expect(matchesProfileKeywords("QWEN 3.8 27b", base)).toBe(true);
  expect(matchesProfileKeywords("DeepSeek", base)).toBe(false);
});

it("matches short GLM IDs inside routing prefixes while preserving minor versions", () => {
  const major = profile("zhipuai/glm-5");
  const current = profile("zhipuai/glm-5.3");
  const flash = profile("zhipuai/glm-5.3-flash");
  const older = profile("zhipuai/glm-5.2");
  for (const id of [
    "zhipu/glm-5.3",
    "tenant-route/GLM_5_3-latest",
    "providerGLM5.3-online",
  ]) {
    expect(suggestModelProfile(id, [major, current, flash, older])).toBe(
      current
    );
  }
  expect(
    suggestModelProfile("zhipu/glm-5.3-flash-fast", [major, current, flash])
  ).toBe(flash);
  expect(
    suggestModelProfile("zhipu/glm-5.30", [major, current])
  ).toBeUndefined();
  expect(
    suggestModelProfile("zhipu/glm-5.2", [major, current])
  ).toBeUndefined();
  expect(
    suggestModelProfile("deploy-qwen3.80-max", [profile("alibaba/qwen3.8-max")])
  ).toBeUndefined();
});
