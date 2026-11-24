// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ConfigItem, ConfigValue } from "./systemConfigData";

type Translate = (key: string, options?: Record<string, unknown>) => string;

export function formatConfigValue(
  item: ConfigItem,
  value: ConfigValue | null,
  t: Translate
): string {
  if (value === null) return t("systemConfig.emptyValue");
  if (typeof value === "boolean")
    return value ? t("systemConfig.on") : t("systemConfig.off");
  if (Array.isArray(value))
    return value.length ? value.join(", ") : t("systemConfig.emptyResourceRefs");
  return item.kind === "number"
    ? String(Number(value.toFixed(2)))
    : String(value);
}
