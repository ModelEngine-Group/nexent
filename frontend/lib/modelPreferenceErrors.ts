// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { TFunction } from "i18next";
import { ApiError } from "@/services/api";

/** Localize structured preference failures without showing provider diagnostics. */
export function modelPreferenceErrorMessage(
  error: unknown,
  t: TFunction
): string {
  if (!(error instanceof ApiError)) return t("modelProfile.preferencesFailed");
  if (error.code === "MODEL_PREFERENCE_VERSION_CONFLICT")
    return t("modelProfile.preferencesConflict");
  const kinds: Record<string, string> = {
    PARAMETER_UNKNOWN: "unknown",
    PARAMETER_VALUE_INVALID: "value",
    PARAMETER_VALUE_REQUIRED: "value",
    FIXED_PARAMETER: "fixed",
    PARAMETER_NOT_EDITABLE: "fixed",
    PARAMETER_DEPENDENCY: "dependency",
  };
  const kind = kinds[String(error.code)];
  if (!kind) return t("modelProfile.preferencesFailed");
  const pointer = error.details?.field;
  const key =
    typeof pointer === "string" ? pointer.split("/").at(-1) : undefined;
  const fallback = t("modelProfile.parameters");
  const field =
    key && /^[a-z][a-z0-9_]*$/.test(key)
      ? t(`modelProfile.parameterLabel.${key}`, { defaultValue: fallback })
      : fallback;
  return t(`modelProfile.validation.${kind}`, { field });
}
