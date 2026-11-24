// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type {
  SystemConfigurationGroup,
  SystemConfigurationItem,
  SystemConfigurationValue,
} from "@/types/systemConfiguration";

export type ConfigGroupId = SystemConfigurationGroup;
export type ConfigValue = SystemConfigurationValue;
export type ConfigItem = SystemConfigurationItem;

export interface ConfigGroup {
  id: ConfigGroupId;
  labelKey: string;
  descriptionKey: string;
}

export const CONFIG_GROUPS: ConfigGroup[] = [
  {
    id: "tenant",
    labelKey: "systemConfig.group.tenant",
    descriptionKey: "systemConfig.group.tenantDesc",
  },
  {
    id: "capacity",
    labelKey: "systemConfig.group.capacity",
    descriptionKey: "systemConfig.group.capacityDesc",
  },
  {
    id: "upload",
    labelKey: "systemConfig.group.upload",
    descriptionKey: "systemConfig.group.uploadDesc",
  },
  {
    id: "runtime",
    labelKey: "systemConfig.group.runtime",
    descriptionKey: "systemConfig.group.runtimeDesc",
  },
];

export function validateConfigValue(
  item: ConfigItem,
  value: ConfigValue | null
): string | null {
  if (value === null || value === undefined)
    return "systemConfig.error.required";
  if (item.kind === "boolean") return null;
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return item.kind === "integer"
      ? "systemConfig.error.positiveInteger"
      : "systemConfig.error.positiveNumber";
  }
  if (item.kind === "integer" && !Number.isInteger(value)) {
    return "systemConfig.error.positiveInteger";
  }
  return null;
}
