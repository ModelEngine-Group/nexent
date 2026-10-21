// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import i18n from "i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import en from "@/public/locales/en/common.json";
import zh from "@/public/locales/zh/common.json";
import { a2aClientService } from "@/services/a2aService";

vi.mock("@/lib/logger", () => ({ default: { error: vi.fn() } }));

beforeEach(async () => {
  await i18n.init({
    lng: "zh",
    fallbackLng: "en",
    keySeparator: false,
    resources: { zh: { translation: zh }, en: { translation: en } },
  });
});

afterEach(() => vi.unstubAllGlobals());

const operations = [
  [
    "URL discovery",
    () => a2aClientService.discoverFromUrl({ url: "https://example.com/card" }),
  ],
  [
    "Nacos discovery",
    () =>
      a2aClientService.discoverFromNacos({
        nacos_config_id: "config",
        agent_names: ["My Agent"],
      }),
  ],
  ["refresh", () => a2aClientService.refreshAgent("1")],
] as const;

describe.each(operations)("%s errors", (_label, operation) => {
  it.each(["zh", "en"])(
    "shows actionable whitespace guidance in %s",
    async (locale) => {
      await i18n.changeLanguage(locale);
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          new Response(
            JSON.stringify({
              detail:
                "Discovery failed: [ValueError] A2A Agent name must not contain spaces or other whitespace",
            }),
            { status: 400 }
          )
        )
      );

      const result = await operation();
      expect(result).toEqual({
        success: false,
        message: i18n.t("a2a.service.nameWhitespace"),
      });
      expect(result.message).not.toBe("a2a.service.nameWhitespace");
      expect(result.message).toContain(
        locale === "zh"
          ? "请修改目标 Agent 名称后重试"
          : "Rename the target Agent"
      );
    }
  );

  it("preserves other API failure details", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: "No source URL available for refresh",
          }),
          { status: 400 }
        )
      )
    );
    expect(await operation()).toEqual({
      success: false,
      message: "No source URL available for refresh",
    });
  });

  it("retains a localized fallback for unknown failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("Unexpected failure"))
    );
    expect(await operation()).toEqual({
      success: false,
      message: i18n.t(
        _label === "refresh"
          ? "a2a.service.refreshFailed"
          : "a2a.service.discoverFailed"
      ),
    });
  });

  it("retains successful discovery and refresh results", async () => {
    const data = { id: 1, name: "Valid-Agent" };
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ status: "success", data }))
        )
    );
    expect(await operation()).toEqual({ success: true, data });
  });
});
