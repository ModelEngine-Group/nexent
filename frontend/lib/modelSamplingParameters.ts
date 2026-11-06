// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ModelParameterRule } from "@/types/modelProfile";

/** Optional sampling controls remain available before provider discovery completes. */
export function outletSamplingRules(
  rules: ModelParameterRule[]
): ModelParameterRule[] {
  return ["temperature", "top_p"].map((key) => ({
    key,
    schema: {
      type: "number",
      minimum: 0,
      maximum: key === "temperature" ? 2 : 1,
    },
    editable: true,
    allowed_scopes: ["outlet"] as Array<"outlet">,
    ui_group: "advanced",
    ...rules.find((rule) => rule.key === key),
    visible: true,
    required: false,
  }));
}

export function outletSamplingValues(
  values: Record<string, unknown>,
  defaults: Record<string, unknown> = {}
) {
  return {
    ...(Object.hasOwn(defaults, "temperature")
      ? { temperature: defaults.temperature }
      : {}),
    ...(Object.hasOwn(defaults, "top_p") ? { top_p: defaults.top_p } : {}),
    ...values,
  };
}

export function samplingComplete(values: Record<string, unknown>) {
  return [values.temperature, values.top_p].every(
    (value) =>
      value == null || (typeof value === "number" && Number.isFinite(value))
  );
}
