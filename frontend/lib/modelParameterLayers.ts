// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** Normalize the existing Agent override payload without copying outlet defaults. */
export const AGENT_PARAMETER_KEYS = [
  "temperature",
  "top_p",
  "top_k",
  "enable_thinking",
  "reasoning_effort",
  "reasoning_budget_tokens",
];

export function agentParameterValues(
  entry: Record<string, unknown> = {}
): Record<string, unknown> {
  if (entry.parameter_values && typeof entry.parameter_values === "object")
    return { ...(entry.parameter_values as Record<string, unknown>) };
  const extra =
    entry.extra_params && typeof entry.extra_params === "object"
      ? (entry.extra_params as Record<string, unknown>)
      : {};
  return Object.fromEntries(
    AGENT_PARAMETER_KEYS.flatMap((key) => {
      const value = Object.hasOwn(extra, key) ? extra[key] : entry[key];
      return value === undefined || value === null ? [] : [[key, value]];
    })
  );
}

export function withAgentParameterValues(
  entry: Record<string, unknown>,
  values: Record<string, unknown>
): Record<string, unknown> {
  const next = { ...entry, parameter_values: { ...values } };
  for (const key of AGENT_PARAMETER_KEYS)
    delete (next as Record<string, unknown>)[key];
  const custom = (entry.extra_params as Record<string, unknown> | undefined)
    ?.__custom__;
  if (custom !== undefined)
    (next as Record<string, unknown>).custom_overrides = custom;
  delete (next as Record<string, unknown>).extra_params;
  return next;
}

/** Conditions only affect presentation; the backend remains authoritative. */
export function parameterIsActive(
  condition: Record<string, unknown> | null | undefined,
  values: Record<string, unknown>
): boolean {
  if (!condition) return true;
  if (Array.isArray(condition.all))
    return condition.all.every((child) => parameterIsActive(child, values));
  if (Array.isArray(condition.any))
    return condition.any.some((child) => parameterIsActive(child, values));
  if (typeof condition.key !== "string") return false;
  if (condition.op === "exists")
    return Object.hasOwn(values, condition.key) === condition.value;
  const value = values[condition.key];
  if (condition.op === "eq") return value === condition.value;
  return (
    condition.op === "in" &&
    Array.isArray(condition.value) &&
    condition.value.includes(value)
  );
}
