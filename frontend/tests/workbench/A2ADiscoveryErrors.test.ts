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

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

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

describe.each(operations.slice(0, 2))(
  "%s backend timeouts",
  (_label, operation) => {
    it.each(["zh", "en"])(
      "localizes backend timeouts in %s",
      async (locale) => {
        await i18n.changeLanguage(locale);
        vi.stubGlobal(
          "fetch",
          vi.fn().mockResolvedValue(
            new Response(
              JSON.stringify({
                detail: "Agent discovery timed out after 10 seconds",
              }),
              { status: 504 }
            )
          )
        );
        expect(await operation()).toEqual({
          success: false,
          message: i18n.t("a2a.service.discoveryTimeout"),
        });
      }
    );

    it.each(["pending fetch", "pending success body", "pending error body"])(
      "waits for the backend without a frontend deadline for %s",
      async (stage) => {
        vi.useFakeTimers();
        let resolveFetch!: (response: Response) => void;
        let completeBody!: () => void;
        const response = new Response("", {
          status: stage === "pending error body" ? 504 : 200,
        });
        if (stage === "pending error body") {
          vi.spyOn(response, "text").mockImplementation(
            () =>
              new Promise<string>((resolve) => {
                completeBody = () =>
                  resolve(
                    JSON.stringify({
                      detail: "Agent discovery timed out after 10 seconds",
                    })
                  );
              })
          );
        } else {
          vi.spyOn(response, "json").mockImplementation(
            () =>
              new Promise<unknown>((resolve) => {
                completeBody = () =>
                  resolve({ status: "error", detail: "Invalid Agent Card" });
              })
          );
        }
        const fetchMock = vi.fn().mockImplementation(() =>
          stage === "pending fetch"
            ? new Promise<Response>((resolve) => {
                resolveFetch = resolve;
              })
            : Promise.resolve(response)
        );
        vi.stubGlobal("fetch", fetchMock);
        let settled = false;
        const result = operation().then((value) => {
          settled = true;
          return value;
        });
        await vi.advanceTimersByTimeAsync(60_000);
        expect(settled).toBe(false);
        expect(vi.getTimerCount()).toBe(0);
        expect(fetchMock.mock.calls[0][1].signal).toBeUndefined();
        expect(fetchMock).toHaveBeenCalledTimes(1);
        if (stage === "pending fetch") {
          resolveFetch(
            new Response(
              JSON.stringify({
                detail: "Agent discovery timed out after 10 seconds",
              }),
              { status: 504 }
            )
          );
        } else {
          completeBody();
        }
        expect(await result).toEqual({
          success: false,
          message:
            stage === "pending success body"
              ? "Invalid Agent Card"
              : i18n.t("a2a.service.discoveryTimeout"),
        });
      }
    );

    it("permits retry after a backend timeout", async () => {
      const fetchMock = vi
        .fn()
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({
              detail: "Agent discovery timed out after 10 seconds",
            }),
            { status: 504 }
          )
        )
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ status: "success", data: { id: 2 } }))
        );
      vi.stubGlobal("fetch", fetchMock);
      expect(await operation()).toEqual({
        success: false,
        message: i18n.t("a2a.service.discoveryTimeout"),
      });
      expect(await operation()).toEqual({ success: true, data: { id: 2 } });
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(fetchMock.mock.calls[1][1].signal).toBeUndefined();
    });
  }
);
