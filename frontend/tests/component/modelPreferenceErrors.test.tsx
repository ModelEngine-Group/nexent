// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { createInstance } from "i18next";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError, fetchWithErrorHandling } from "@/services/api";
import { modelPreferenceErrorMessage } from "@/lib/modelPreferenceErrors";
import en from "@/public/locales/en/common.json";
import zh from "@/public/locales/zh/common.json";

beforeEach(() => vi.unstubAllGlobals());
afterEach(() => vi.unstubAllGlobals());

it("preserves validation field pointers and existing nested details through HTTP transport", async () => {
  for (const envelope of ["detail", "message"])
    for (const detail of [
      { code: "PARAMETER_DEPENDENCY", field: "/reasoning_effort" },
      {
        code: "PARAMETER_VALUE_INVALID",
        details: { field: "/temperature", marker: false },
      },
    ]) {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          new Response(JSON.stringify({ [envelope]: detail }), {
            status: 422,
          })
        )
      );
      await expect(
        fetchWithErrorHandling("/api/preferences")
      ).rejects.toMatchObject({
        code: detail.code,
        details: detail.details ?? { field: detail.field },
      });
    }
});

it.each(["zh", "en"])(
  "localizes known validation and real revision conflicts in %s without raw error leakage",
  async (lng) => {
    const i18n = createInstance();
    await i18n.init({
      lng,
      resources: { en: { translation: en }, zh: { translation: zh } },
    });
    for (const [code, kind] of [
      ["PARAMETER_DEPENDENCY", "dependency"],
      ["PARAMETER_VALUE_INVALID", "value"],
      ["PARAMETER_VALUE_REQUIRED", "value"],
      ["PARAMETER_UNKNOWN", "unknown"],
      ["FIXED_PARAMETER", "fixed"],
      ["PARAMETER_NOT_EDITABLE", "fixed"],
    ]) {
      const result = modelPreferenceErrorMessage(
        new ApiError(code, "private diagnostic", {
          field: "/reasoning_effort",
        }),
        i18n.t
      );
      expect(result).toBe(
        i18n.t(`modelProfile.validation.${kind}`, {
          field: i18n.t("modelProfile.parameterLabel.reasoning_effort"),
        })
      );
      expect(result).not.toMatch(
        /private diagnostic|latest revision|最新配置版本/
      );
    }
    expect(
      modelPreferenceErrorMessage(
        new ApiError("MODEL_PREFERENCE_VERSION_CONFLICT", "private"),
        i18n.t
      )
    ).toBe(i18n.t("modelProfile.preferencesConflict"));
    expect(modelPreferenceErrorMessage(new Error("private"), i18n.t)).toBe(
      i18n.t("modelProfile.preferencesFailed")
    );
    expect(
      modelPreferenceErrorMessage(new ApiError("UNKNOWN", "private"), i18n.t)
    ).toBe(i18n.t("modelProfile.preferencesFailed"));
    expect(
      modelPreferenceErrorMessage(
        new ApiError("PARAMETER_DEPENDENCY", "private", {
          field: "/private~1credential",
        }),
        i18n.t
      )
    ).not.toContain("private");
  }
);
