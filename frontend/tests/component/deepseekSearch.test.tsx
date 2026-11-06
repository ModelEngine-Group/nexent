// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { afterEach, describe, expect, it, vi } from "vitest";
import { validateTool } from "@/services/agentConfigService";
import {
  buildCitationDisplayIndexMap,
  getCitationKey,
  withCitationDisplayIndices,
} from "@/lib/citationDisplay";

vi.mock("@/lib/auth", () => ({
  getAuthHeaders: () => ({ Authorization: "Bearer synthetic-session" }),
  fetchWithAuth: vi.fn(),
}));
vi.mock("@/lib/logger", () => ({
  default: { error: vi.fn(), warn: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));

afterEach(() => vi.unstubAllGlobals());

describe("DeepSeek validation serialization", () => {
  it("restores DeepSeek references without colliding with existing search tools", () => {
    const sources: Array<{ toolSign: string; citeIndex: number; url: string }> =
      JSON.parse(
        JSON.stringify([
          { toolSign: "o", citeIndex: 1, url: "https://example.com/deepseek" },
          { toolSign: "a", citeIndex: 1, url: "https://example.com/knowledge" },
        ])
      );
    const indices = buildCitationDisplayIndexMap(
      [{ type: "text", text: "[[o1]] and [[a1]] then [[o1]]" }],
      sources
    );
    const displayed = withCitationDisplayIndices(sources, indices);
    expect(displayed.map(getCitationKey)).toEqual(["o1", "a1"]);
    expect(displayed.map((source) => source.displayIndex)).toEqual([1, 2]);
    expect(displayed[0].url).toBe("https://example.com/deepseek");
  });

  it.each(["zh", "en"] as const)(
    "carries current %s language and the quality switch",
    async (language) => {
      const fetch = vi.fn().mockResolvedValue({ json: async () => [] });
      vi.stubGlobal("fetch", fetch);
      await validateTool(
        "deepseek_search",
        "local",
        "",
        { query: "topic site:github.com" },
        {
          deepseek_api_key: "synthetic-provider-key",
          only_high_quality: true,
          max_results: 10,
        },
        language
      );
      const body = JSON.parse(fetch.mock.calls[0][1].body);
      expect(body.language).toBe(language);
      expect(body.params).toEqual({
        deepseek_api_key: "synthetic-provider-key",
        only_high_quality: true,
        max_results: 10,
      });
      expect(body.inputs).toEqual({ query: "topic site:github.com" });
      expect(body.inputs).not.toHaveProperty("language");
      expect(body.inputs).not.toHaveProperty("deepseek_api_key");
    }
  );

  it("preserves false and the default language for existing callers", async () => {
    const fetch = vi.fn().mockResolvedValue({ json: async () => [] });
    vi.stubGlobal("fetch", fetch);
    await validateTool(
      "deepseek_search",
      "local",
      "",
      { query: "topic" },
      { only_high_quality: false }
    );
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toMatchObject({
      language: "zh",
      params: { only_high_quality: false },
    });
  });
});
