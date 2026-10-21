// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** Format model capacity using decimal token units; omit unavailable values. */
export function formatModelTokenLabel(tokens?: number | null): string | null {
  if (tokens == null || !Number.isFinite(tokens) || tokens <= 0) return null;

  const units = ["", "k", "M", "B"];
  let value = tokens;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  let rounded = Number(value.toFixed(2));
  if (rounded >= 1000 && unit < units.length - 1) {
    rounded = Number((rounded / 1000).toFixed(2));
    unit += 1;
  }
  return `${rounded}${units[unit]}`;
}
