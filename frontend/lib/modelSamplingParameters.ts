// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ModelParameterRule } from "@/types/modelProfile";

export const TOP_P_STEP = 0.01;

export function validTopP(
  value: unknown,
  schema: Record<string, unknown> = {}
) {
  if (value == null) return true;
  return (
    typeof value === "number" &&
    value > 0 &&
    value <= 1 &&
    (typeof schema.minimum !== "number" || value >= schema.minimum) &&
    (typeof schema.maximum !== "number" || value <= schema.maximum) &&
    (!Array.isArray(schema.enum) || schema.enum.includes(value)) &&
    (!Object.hasOwn(schema, "const") || schema.const === value) &&
    (![schema.type].flat().includes("integer") ||
      [schema.type].flat().includes("number") ||
      Number.isInteger(value))
  );
}

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

export function samplingComplete(
  values: Record<string, unknown>,
  rules: ModelParameterRule[] = []
) {
  return (
    (values.temperature == null ||
      (typeof values.temperature === "number" &&
        Number.isFinite(values.temperature))) &&
    validTopP(values.top_p, rules.find((rule) => rule.key === "top_p")?.schema)
  );
}
