// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** Read a declared output capability independently of request parameter defaults. */
export function profileOutputLimit(
  context: unknown,
  windowOverride?: number | null
): number | undefined {
  if (!context || typeof context !== "object" || !("output_limit" in context))
    return undefined;
  const output = context.output_limit;
  if (
    typeof output !== "number" ||
    !Number.isSafeInteger(output) ||
    output <= 0
  )
    return undefined;
  const window =
    windowOverride ??
    ("combined_window" in context ? context.combined_window : undefined);
  return typeof window === "number" &&
    Number.isSafeInteger(window) &&
    window > 0
    ? Math.min(output, window)
    : output;
}
