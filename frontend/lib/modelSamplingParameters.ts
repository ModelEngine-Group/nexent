// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ModelParameterRule } from "@/types/modelProfile";

export const TOP_P_STEP = 0.01;

export const SAMPLING_FIELDS = ["temperature", "top_p"] as const;
export type SamplingField = (typeof SAMPLING_FIELDS)[number];

export function isSamplingField(key: string): key is SamplingField {
  return key === "temperature" || key === "top_p";
}

export function samplingErrorKey(field: SamplingField) {
  return field === "temperature" ? "modelParams.temperatureInvalid" : "modelParams.topPInvalid";
}

export function validSampling(
  field: SamplingField,
  value: unknown,
  schema: Record<string, unknown> = {}
) {
  if (value == null) return true;
  return (
    typeof value === "number" &&
    (field === "temperature" ? value >= 0 && value <= 2 : value > 0 && value <= 1) &&
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
  return SAMPLING_FIELDS.every((field) =>
    validSampling(field, values[field], rules.find((rule) => rule.key === field)?.schema)
  );
}
