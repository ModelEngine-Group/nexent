// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type {
  SystemConfigurationGroup,
  SystemConfigurationItem,
  SystemConfigurationValue,
} from "@/types/systemConfiguration";

export type ConfigGroupId = SystemConfigurationGroup;
export type ConfigValue = SystemConfigurationValue;
export type ConfigItem = SystemConfigurationItem;

const RESOURCE_REF = /^(?:(?:tool|skill|tenant_skill_repository|tenant_mcp_repository):[1-9][0-9]*|nexent_official_skill:(?:[A-Za-z0-9_.~-]|%[0-9A-F]{2})+)$/;

export function configValuesEqual(left: ConfigValue | null, right: ConfigValue) {
  if (Array.isArray(left) && Array.isArray(right)) {
    const sortedRight = [...right].sort();
    return (
      left.length === right.length &&
      [...left].sort().every((ref, index) => ref === sortedRight[index])
    );
  }
  return left === right;
}

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
  if (item.kind === "resource_refs") {
    return Array.isArray(value) &&
      value.length <= 200 &&
      new Set(value).size === value.length &&
      value.every((ref) => ref.length <= 1024 && RESOURCE_REF.test(ref))
      ? null
      : "systemConfig.error.resourceRefs";
  }
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
